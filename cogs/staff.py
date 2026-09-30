import os
import sqlite3
import time
import traceback
from datetime import timedelta
from typing import Optional

import discord
from discord.ext import commands, tasks

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
ROLE_P1 = 1554795293382410312
ROLE_P2 = 1554795294519070781
ROLE_P3 = 1554795294577917963
ROLE_P4 = 1554795294929981492

NIVEAUX = {ROLE_P1: 1, ROLE_P2: 2, ROLE_P3: 3, ROLE_P4: 4}

# Salon où sont envoyés les logs de modération (mets l'ID ici, 0 = pas de logs)
LOGS_MOD_CHANNEL_ID = 1554797148288323636

MAX_TIMEOUT = timedelta(days=28)  # limite imposée par Discord pour un mute
DB_PATH = "data/moderation.db"

# Sanction automatique des warns : mute automatique à chaque multiple de ce nombre
# (ex: 3 -> mute au 3e, 6e, 9e warn...). Mets 0 pour désactiver.
SEUIL_MUTE_AUTO = 3
DUREE_MUTE_AUTO_MIN = 60  # durée du mute automatique, en minutes

COULEUR_MOD = 0xc0392b
COULEUR_OK = 0x1f8b4c


# ─────────────────────────────────────────────
# Niveaux de permission
# ─────────────────────────────────────────────
def get_niveau(membre: discord.Member) -> int:
    """Renvoie le niveau d'un membre : 0 (rien), 1 à 4 (P1 à P4), 5 (propriétaire du serveur)."""
    if membre.id == membre.guild.owner_id:
        return 5
    if membre.guild_permissions.administrator:
        return 4
    niveau = 0
    for role in membre.roles:
        niveau = max(niveau, NIVEAUX.get(role.id, 0))
    return niveau


def niveau_requis(niveau: int):
    """Décorateur : la commande n'est utilisable qu'à partir du niveau Px demandé."""
    async def predicate(ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("Cette commande est utilisable uniquement sur le serveur.")
        if get_niveau(ctx.author) >= niveau:
            return True
        raise commands.CheckFailure(f"Il faut être **P{niveau}** minimum pour utiliser cette commande.")
    return commands.check(predicate)


# ─────────────────────────────────────────────
# Fonctions utilitaires
# ─────────────────────────────────────────────
def parser_duree(texte: str, autoriser_perm: bool = False):
    """
    Transforme un texte en durée.
      "10"  -> 10 minutes (sans unité = minutes)
      "30m" -> 30 minutes / "2h" -> 2 heures / "7d" -> 7 jours
      "perm" -> None (permanent), seulement si autoriser_perm=True
    """
    t = texte.lower().strip()
    if autoriser_perm and t in ("perm", "permanent"):
        return None

    secondes_par_unite = {"m": 60, "h": 3600, "d": 86400}
    unite = "m"
    if t and t[-1] in secondes_par_unite:
        unite = t[-1]
        t = t[:-1]

    if not t.isdigit() or int(t) <= 0:
        exemple = "`10`, `30m`, `2h`, `7d`" + (" ou `perm`" if autoriser_perm else "")
        raise ValueError(f"Durée invalide. Exemples : {exemple} (sans unité = minutes).")

    return timedelta(seconds=int(t) * secondes_par_unite[unite])


def duree_lisible(delta: timedelta) -> str:
    """Ex: 'timedelta(minutes=135)' -> '2h 15min'."""
    total = int(delta.total_seconds())
    jours, reste = divmod(total, 86400)
    heures, reste = divmod(reste, 3600)
    minutes, _ = divmod(reste, 60)
    morceaux = []
    if jours:
        morceaux.append(f"{jours}j")
    if heures:
        morceaux.append(f"{heures}h")
    if minutes or not morceaux:
        morceaux.append(f"{minutes}min")
    return " ".join(morceaux)


async def prevenir_en_mp(membre, texte: str):
    """Envoie un MP au membre (ignore l'erreur s'il a ses MP fermés)."""
    try:
        await membre.send(texte)
    except (discord.Forbidden, discord.HTTPException):
        pass


# ─────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────
class Staff(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Base de données pour les bans temporaires (survit aux redémarrages du bot)
        os.makedirs("data", exist_ok=True)
        self.db = sqlite3.connect(DB_PATH)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS tempbans ("
            "guild_id INTEGER, user_id INTEGER, unban_at INTEGER, "
            "PRIMARY KEY (guild_id, user_id))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS warns ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, "
            "moderator_id INTEGER, reason TEXT, created_at INTEGER)"
        )
        self.db.commit()

    async def cog_load(self):
        self.verifier_bans.start()

    async def cog_unload(self):
        self.verifier_bans.cancel()
        self.db.close()

    # ── Logs de modération ──
    async def log_mod(self, guild, titre, couleur, cible=None, moderateur=None, raison=None, champs=None):
        if not LOGS_MOD_CHANNEL_ID:
            return
        salon = guild.get_channel(LOGS_MOD_CHANNEL_ID)
        if salon is None:
            return

        embed = discord.Embed(title=titre, color=couleur, timestamp=discord.utils.utcnow())
        if cible is not None:
            embed.add_field(name="Cible", value=f"<@{cible.id}> (`{cible.id}`)", inline=True)
        if moderateur is not None:
            embed.add_field(name="Modérateur", value=moderateur.mention, inline=True)
        for nom, valeur in (champs or []):
            embed.add_field(name=nom, value=valeur, inline=True)
        if raison:
            embed.add_field(name="Raison", value=raison, inline=False)

        try:
            await salon.send(embed=embed)
        except discord.HTTPException:
            pass

    # ── Sécurités : est-ce qu'on a le droit de toucher à cette personne ? ──
    async def verifier_cible(self, ctx, cible: discord.Member) -> bool:
        if cible.id == ctx.author.id:
            await ctx.send("❌ Tu ne peux pas t'appliquer ça à toi-même.", delete_after=8)
            return False
        if cible.id == self.bot.user.id:
            await ctx.send("❌ Je ne peux pas me sanctionner moi-même.", delete_after=8)
            return False
        if get_niveau(cible) >= get_niveau(ctx.author):
            await ctx.send("❌ Tu ne peux pas sanctionner quelqu'un de même niveau ou de niveau supérieur.", delete_after=8)
            return False
        if cible.top_role >= ctx.guild.me.top_role:
            await ctx.send("❌ Mon rôle est trop bas pour agir sur ce membre (remonte le rôle du bot).", delete_after=8)
            return False
        return True

    # ─────────────────────────────────────────
    # P1 : mute / unmute / clear
    # ─────────────────────────────────────────
    @commands.command(usage="@user <durée en minutes> [raison]")
    @niveau_requis(1)
    async def mute(self, ctx, membre: discord.Member, duree: str, *, raison: str = "Aucune raison"):
        try:
            delta = parser_duree(duree)
        except ValueError as e:
            return await ctx.send(f"❌ {e}", delete_after=10)

        if delta > MAX_TIMEOUT:
            return await ctx.send("❌ Un mute ne peut pas dépasser 28 jours.", delete_after=8)
        if not await self.verifier_cible(ctx, membre):
            return

        await membre.timeout(delta, reason=f"{raison} (par {ctx.author})"[:512])
        await ctx.send(f"🔇 {membre.mention} est mute pendant **{duree_lisible(delta)}**.\nRaison : {raison}")
        await self.log_mod(
            ctx.guild, "🔇 Mute", COULEUR_MOD, membre, ctx.author, raison,
            champs=[("Durée", duree_lisible(delta))],
        )

    @commands.command(usage="@user")
    @niveau_requis(1)
    async def unmute(self, ctx, membre: discord.Member):
        if not membre.is_timed_out():
            return await ctx.send("❌ Ce membre n'est pas mute.", delete_after=8)

        await membre.timeout(None, reason=f"Unmute par {ctx.author}")
        await ctx.send(f"🔊 {membre.mention} n'est plus mute.")
        await self.log_mod(ctx.guild, "🔊 Unmute", COULEUR_OK, membre, ctx.author)

    @commands.command(usage="[@user] <nombre>")
    @niveau_requis(1)
    async def clear(self, ctx, membre: Optional[discord.Member], nombre: int):
        """!clear 20 -> supprime les 20 derniers messages | !clear @user 5 -> les 5 derniers de ce membre"""
        if not 1 <= nombre <= 100:
            return await ctx.send("❌ Le nombre doit être compris entre 1 et 100.", delete_after=8)

        # On supprime d'abord le message de commande pour qu'il ne soit pas compté
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        if membre is None:
            supprimes = await ctx.channel.purge(limit=nombre)
            nb = len(supprimes)
        else:
            # Discord ne permet pas de supprimer en masse les messages de +14 jours
            limite = discord.utils.utcnow() - timedelta(days=14)
            a_supprimer = []
            async for msg in ctx.channel.history(limit=1000):
                if msg.created_at < limite:
                    break
                if msg.author.id == membre.id:
                    a_supprimer.append(msg)
                    if len(a_supprimer) >= nombre:
                        break
            if a_supprimer:
                await ctx.channel.delete_messages(a_supprimer)
            nb = len(a_supprimer)

        cible_txt = f" de {membre.mention}" if membre else ""
        await ctx.send(f"🧹 {nb} message(s){cible_txt} supprimé(s).", delete_after=5)
        await self.log_mod(
            ctx.guild, "🧹 Clear", COULEUR_MOD, membre, ctx.author,
            champs=[("Salon", ctx.channel.mention), ("Messages supprimés", str(nb))],
        )

    # ─────────────────────────────────────────
    # P2 : kick
    # ─────────────────────────────────────────
    @commands.command(usage="@user [raison]")
    @niveau_requis(2)
    async def kick(self, ctx, membre: discord.Member, *, raison: str = "Aucune raison"):
        if not await self.verifier_cible(ctx, membre):
            return

        await prevenir_en_mp(membre, f"👢 Tu as été expulsé de **{ctx.guild.name}**.\nRaison : {raison}")
        await membre.kick(reason=f"{raison} (par {ctx.author})"[:512])
        await ctx.send(f"👢 **{membre}** a été expulsé.\nRaison : {raison}")
        await self.log_mod(ctx.guild, "👢 Kick", COULEUR_MOD, membre, ctx.author, raison)

    # ─────────────────────────────────────────
    # P2 : warn / warns / unwarn / slowmode
    # ─────────────────────────────────────────
    @commands.command(usage="@user [raison]")
    @niveau_requis(2)
    async def warn(self, ctx, membre: discord.Member, *, raison: str = "Aucune raison"):
        if not await self.verifier_cible(ctx, membre):
            return

        raison = raison[:500]
        self.db.execute(
            "INSERT INTO warns (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, membre.id, ctx.author.id, raison, int(time.time())),
        )
        self.db.commit()
        total = self.db.execute(
            "SELECT COUNT(*) FROM warns WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        ).fetchone()[0]

        await prevenir_en_mp(
            membre,
            f"⚠️ Tu as reçu un avertissement sur **{ctx.guild.name}**.\n"
            f"Raison : {raison}\nTotal : {total} avertissement(s).",
        )
        await ctx.send(f"⚠️ {membre.mention} a reçu un avertissement (**{total}** au total).\nRaison : {raison}")
        await self.log_mod(
            ctx.guild, "⚠️ Warn", COULEUR_MOD, membre, ctx.author, raison,
            champs=[("Total", str(total))],
        )

        # Sanction automatique : mute à chaque multiple du seuil
        if SEUIL_MUTE_AUTO and total % SEUIL_MUTE_AUTO == 0:
            delta = timedelta(minutes=DUREE_MUTE_AUTO_MIN)
            try:
                await membre.timeout(delta, reason=f"Sanction automatique : {total} avertissements")
            except discord.HTTPException:
                return
            await ctx.send(
                f"🔇 {membre.mention} est automatiquement mute **{duree_lisible(delta)}** ({total} avertissements)."
            )
            await self.log_mod(
                ctx.guild, "🔇 Mute automatique", COULEUR_MOD, membre, None,
                f"{total} avertissements", champs=[("Durée", duree_lisible(delta))],
            )

    @commands.command(usage="@user")
    @niveau_requis(2)
    async def warns(self, ctx, membre: discord.Member):
        lignes = self.db.execute(
            "SELECT id, moderator_id, reason, created_at FROM warns "
            "WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT 10",
            (ctx.guild.id, membre.id),
        ).fetchall()

        if not lignes:
            return await ctx.send(f"✅ {membre.mention} n'a aucun avertissement.")

        total = self.db.execute(
            "SELECT COUNT(*) FROM warns WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        ).fetchone()[0]

        detail = "\n\n".join(
            f"**#{warn_id}** · <t:{ts}:d> · par <@{mod_id}>\n└ {reason[:200]}"
            for warn_id, mod_id, reason, ts in lignes
        )
        embed = discord.Embed(
            description=(
                f"# ⚠️ Avertissements de {membre.display_name}\n"
                f"**{total}** au total (les 10 derniers sont affichés).\n\n{detail}"
            ),
            color=COULEUR_MOD,
        )
        await ctx.send(embed=embed)

    @commands.command(usage="<ID de l'avertissement>")
    @niveau_requis(2)
    async def unwarn(self, ctx, warn_id: int):
        ligne = self.db.execute(
            "SELECT user_id, reason FROM warns WHERE id = ? AND guild_id = ?", (warn_id, ctx.guild.id)
        ).fetchone()
        if ligne is None:
            return await ctx.send("❌ Aucun avertissement avec cet ID (visible via `!warns @user`).", delete_after=8)

        self.db.execute("DELETE FROM warns WHERE id = ?", (warn_id,))
        self.db.commit()

        await ctx.send(f"✅ Avertissement **#{warn_id}** supprimé.")
        await self.log_mod(
            ctx.guild, "🗑️ Unwarn", COULEUR_OK, discord.Object(id=ligne[0]), ctx.author,
            champs=[("Warn supprimé", f"#{warn_id}")],
        )

    @commands.command(usage="<secondes, 0 pour désactiver> [#salon]")
    @niveau_requis(2)
    async def slowmode(self, ctx, secondes: int, salon: Optional[discord.TextChannel] = None):
        salon = salon or ctx.channel
        if not 0 <= secondes <= 21600:
            return await ctx.send("❌ Le slowmode doit être entre 0 et 21600 secondes (6h).", delete_after=8)

        await salon.edit(slowmode_delay=secondes, reason=f"Slowmode par {ctx.author}")

        if secondes == 0:
            await ctx.send(f"⏱️ Slowmode désactivé dans {salon.mention}.")
        else:
            await ctx.send(f"⏱️ Slowmode activé dans {salon.mention} : **{secondes}s** entre chaque message.")
        await self.log_mod(
            ctx.guild, "⏱️ Slowmode", COULEUR_MOD, None, ctx.author,
            champs=[("Salon", salon.mention), ("Délai", f"{secondes}s" if secondes else "Désactivé")],
        )

    # ─────────────────────────────────────────
    # P3 : ban / unban
    # ─────────────────────────────────────────
    @commands.command(usage="@user <durée|perm> [raison]")
    @niveau_requis(3)
    async def ban(self, ctx, membre: discord.Member, duree: str, *, raison: str = "Aucune raison"):
        try:
            delta = parser_duree(duree, autoriser_perm=True)
        except ValueError as e:
            return await ctx.send(f"❌ {e}", delete_after=10)

        if not await self.verifier_cible(ctx, membre):
            return

        texte_duree = "définitivement" if delta is None else f"pour {duree_lisible(delta)}"
        await prevenir_en_mp(membre, f"🔨 Tu as été banni de **{ctx.guild.name}** {texte_duree}.\nRaison : {raison}")
        await ctx.guild.ban(membre, reason=f"{raison} (par {ctx.author})"[:512])

        # Ban temporaire : on note la date de fin. Ban permanent : on efface toute ancienne date.
        if delta is None:
            self.db.execute("DELETE FROM tempbans WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id))
        else:
            fin = int(time.time() + delta.total_seconds())
            self.db.execute(
                "INSERT OR REPLACE INTO tempbans (guild_id, user_id, unban_at) VALUES (?, ?, ?)",
                (ctx.guild.id, membre.id, fin),
            )
        self.db.commit()

        await ctx.send(f"🔨 **{membre}** a été banni {texte_duree}.\nRaison : {raison}")
        await self.log_mod(
            ctx.guild, "🔨 Ban", COULEUR_MOD, membre, ctx.author, raison,
            champs=[("Durée", "Permanent" if delta is None else duree_lisible(delta))],
        )

    @commands.command(usage="<ID de l'utilisateur>")
    @niveau_requis(3)
    async def unban(self, ctx, utilisateur: discord.User):
        try:
            await ctx.guild.unban(utilisateur, reason=f"Unban par {ctx.author}")
        except discord.NotFound:
            return await ctx.send("❌ Cet utilisateur n'est pas banni.", delete_after=8)

        self.db.execute("DELETE FROM tempbans WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, utilisateur.id))
        self.db.commit()

        await ctx.send(f"✅ **{utilisateur}** a été débanni.")
        await self.log_mod(ctx.guild, "✅ Unban", COULEUR_OK, utilisateur, ctx.author)

    # ── Tâche automatique : débannit ceux dont le ban temporaire est terminé ──
    @tasks.loop(minutes=1)
    async def verifier_bans(self):
        maintenant = int(time.time())
        lignes = self.db.execute(
            "SELECT guild_id, user_id FROM tempbans WHERE unban_at <= ?", (maintenant,)
        ).fetchall()

        for guild_id, user_id in lignes:
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            try:
                await guild.unban(discord.Object(id=user_id), reason="Fin du bannissement temporaire")
            except discord.NotFound:
                pass  # déjà débanni à la main
            except discord.HTTPException:
                continue  # on réessaiera à la minute suivante

            self.db.execute("DELETE FROM tempbans WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            await self.log_mod(
                guild, "⏱️ Fin de ban temporaire", COULEUR_OK, discord.Object(id=user_id),
            )
        self.db.commit()

    @verifier_bans.before_loop
    async def avant_verifier_bans(self):
        await self.bot.wait_until_ready()

    # ─────────────────────────────────────────
    # Message explicatif des permissions (à poster dans un salon staff)
    # ─────────────────────────────────────────
    @commands.command()
    @niveau_requis(4)
    async def post_perms(self, ctx):
        if SEUIL_MUTE_AUTO:
            duree_auto = duree_lisible(timedelta(minutes=DUREE_MUTE_AUTO_MIN))
            ligne_auto = f" → mute auto de {duree_auto} tous les {SEUIL_MUTE_AUTO} warns"
        else:
            ligne_auto = ""

        embed = discord.Embed(
            description=(
                "# 🛡️ Permissions du staff\n"
                "Les rôles **P1 à P4** n'ont aucune permission Discord : tout passe par les commandes du bot. "
                "Chaque niveau **hérite** des commandes du niveau précédent.\n\n"

                "## 🟢 P1 — Modération de base\n"
                "• `!mute @user <durée> [raison]` → durée en minutes (`10`) ou `30m`, `2h`, `7d` (max 28j)\n"
                "• `!unmute @user` → retire le mute\n"
                "• `!clear <nombre>` → supprime les X derniers messages du salon (max 100)\n"
                "• `!clear @user <nombre>` → supprime les X derniers messages d'un membre\n\n"

                "## 🟡 P2 — + Kick, warn et slowmode\n"
                "*Tout P1, plus :*\n"
                "• `!kick @user [raison]` → expulse un membre\n"
                f"• `!warn @user [raison]` → avertit un membre{ligne_auto}\n"
                "• `!warns @user` → liste les avertissements d'un membre\n"
                "• `!unwarn <ID>` → supprime un avertissement\n"
                "• `!slowmode <secondes> [#salon]` → ralentit un salon (`0` pour désactiver)\n\n"

                "## 🟠 P3 — + Ban\n"
                "*Tout P2, plus :*\n"
                "• `!ban @user <durée|perm> [raison]` → ban temporaire (`7d`) ou définitif (`perm`)\n"
                "• `!unban <ID>` → lève un ban\n\n"

                "## 🔴 P4 — Admin\n"
                "*Tout P3, plus :* accès complet au serveur et à toutes les commandes admin du bot.\n\n"

                "## 📌 À respecter\n"
                "• Tu ne peux pas sanctionner quelqu'un de **même niveau ou supérieur**\n"
                "• Mets toujours une **raison**, elle apparaît dans les logs\n"
                "• Toutes les actions sont **enregistrées** dans les logs staff\n"
                "• Un doute ? **Warn avant de ban**, ou demande à un P supérieur"
            ),
            color=COULEUR_OK,
        )

        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        await ctx.send(embed=embed)

    # ─────────────────────────────────────────
    # Gestion des erreurs (messages clairs au lieu de silence)
    # ─────────────────────────────────────────
    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send(f"❌ {error}", delete_after=8)
        elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
            usage = ctx.command.usage or ""
            await ctx.send(f"❌ Utilisation : `!{ctx.command.name} {usage}`", delete_after=10)
        elif isinstance(error, commands.CommandInvokeError) and isinstance(error.original, discord.Forbidden):
            await ctx.send("❌ Il me manque une permission, ou mon rôle est trop bas.", delete_after=10)
        else:
            traceback.print_exception(type(error), error, error.__traceback__)


async def setup(bot):
    await bot.add_cog(Staff(bot))