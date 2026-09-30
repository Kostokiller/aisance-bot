import os
import random
import sqlite3
import time
import traceback
from typing import Optional

import discord
from discord.ext import commands

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
# IDs des rôles à donner automatiquement (0 = désactivé tant que tu n'as pas mis l'ID)
ROLE_ACTIF_ID = 1554793780828446720
ROLE_CONFIRME_ID = 1554793783525122118

# Niveau à atteindre pour obtenir chaque rôle
NIVEAU_ACTIF = 5
NIVEAU_CONFIRME = 15

ROLES_PAR_NIVEAU = {
    NIVEAU_ACTIF: ROLE_ACTIF_ID,
    NIVEAU_CONFIRME: ROLE_CONFIRME_ID,
}

# Gain d'XP par message (aléatoire entre les deux valeurs)
XP_MIN = 15
XP_MAX = 25
COOLDOWN_SECONDES = 60   # 1 gain d'XP maximum par minute et par membre (anti-spam)
LONGUEUR_MIN = 4         # les messages plus courts que ça ne rapportent rien

# Salons où l'on ne gagne pas d'XP (ajoute des IDs ici, ex: [123456, 789012])
SALONS_IGNORES = []

DB_PATH = "data/leveling.db"
COULEUR = 0x1f8b4c


# ─────────────────────────────────────────────
# Maths des niveaux
# ─────────────────────────────────────────────
def xp_pour_niveau(niveau: int) -> int:
    """XP total nécessaire pour atteindre un niveau (niv 1 = 100, niv 5 = 2500, niv 10 = 10000...)."""
    return 100 * niveau * niveau


def niveau_depuis_xp(xp: int) -> int:
    return int((xp / 100) ** 0.5)


def barre_progression(actuel: int, total: int, taille: int = 12) -> str:
    rempli = int(taille * actuel / total) if total else 0
    return "█" * rempli + "░" * (taille - rempli)


# ─────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────
class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}  # (guild_id, user_id) -> heure du dernier gain d'XP

        os.makedirs("data", exist_ok=True)
        self.db = sqlite3.connect(DB_PATH)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS levels ("
            "guild_id INTEGER, user_id INTEGER, xp INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (guild_id, user_id))"
        )
        self.db.commit()

    async def cog_unload(self):
        self.db.close()

    # ── Base de données ──
    def get_xp(self, guild_id: int, user_id: int) -> int:
        ligne = self.db.execute(
            "SELECT xp FROM levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ).fetchone()
        return ligne[0] if ligne else 0

    def set_xp(self, guild_id: int, user_id: int, xp: int):
        self.db.execute(
            "INSERT OR REPLACE INTO levels (guild_id, user_id, xp) VALUES (?, ?, ?)",
            (guild_id, user_id, xp),
        )
        self.db.commit()

    def get_rang(self, guild_id: int, xp: int) -> int:
        return self.db.execute(
            "SELECT COUNT(*) + 1 FROM levels WHERE guild_id = ? AND xp > ?", (guild_id, xp)
        ).fetchone()[0]

    # ── Rôles automatiques ──
    async def synchroniser_roles(self, membre: discord.Member, niveau: int, retirer: bool = False):
        """Donne les rôles mérités. Si retirer=True, retire aussi ceux qui ne sont plus mérités."""
        ajoutes = []
        for seuil, role_id in ROLES_PAR_NIVEAU.items():
            if not role_id:
                continue
            role = membre.guild.get_role(role_id)
            if role is None:
                continue

            try:
                if niveau >= seuil and role not in membre.roles:
                    await membre.add_roles(role, reason=f"Niveau {niveau} atteint")
                    ajoutes.append(role)
                elif retirer and niveau < seuil and role in membre.roles:
                    await membre.remove_roles(role, reason=f"Niveau {niveau} : rôle plus mérité")
            except discord.HTTPException:
                pass  # rôle du bot trop bas ou permission manquante
        return ajoutes

    # ── Gain d'XP à chaque message ──
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if message.channel.id in SALONS_IGNORES:
            return
        if len(message.content) < LONGUEUR_MIN:
            return

        # On ignore les commandes (!rank, !top...)
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        cle = (message.guild.id, message.author.id)
        maintenant = time.time()
        if maintenant - self.cooldowns.get(cle, 0) < COOLDOWN_SECONDES:
            return
        self.cooldowns[cle] = maintenant

        ancien_xp = self.get_xp(message.guild.id, message.author.id)
        nouveau_xp = ancien_xp + random.randint(XP_MIN, XP_MAX)
        self.set_xp(message.guild.id, message.author.id, nouveau_xp)

        ancien_niveau = niveau_depuis_xp(ancien_xp)
        nouveau_niveau = niveau_depuis_xp(nouveau_xp)
        if nouveau_niveau > ancien_niveau:
            await self.niveau_superieur(message, nouveau_niveau)

    async def niveau_superieur(self, message: discord.Message, niveau: int):
        roles_gagnes = await self.synchroniser_roles(message.author, niveau)

        texte = f"🎉 {message.author.mention} passe **niveau {niveau}** !"
        if roles_gagnes:
            texte += "\n🏅 Nouveau rôle : " + ", ".join(r.mention for r in roles_gagnes)

        try:
            await message.channel.send(
                texte,
                allowed_mentions=discord.AllowedMentions.none(),  # pas de notif à chaque niveau
                delete_after=None if roles_gagnes else 20,
            )
        except discord.HTTPException:
            pass

    # ─────────────────────────────────────────
    # Commandes
    # ─────────────────────────────────────────
    @commands.command(usage="[@user]")
    async def rank(self, ctx, membre: Optional[discord.Member] = None):
        """Affiche le niveau et l'XP d'un membre (toi par défaut)."""
        membre = membre or ctx.author
        xp = self.get_xp(ctx.guild.id, membre.id)
        niveau = niveau_depuis_xp(xp)

        base = xp_pour_niveau(niveau)
        suivant = xp_pour_niveau(niveau + 1)
        actuel = xp - base
        total = suivant - base
        rang = self.get_rang(ctx.guild.id, xp)

        embed = discord.Embed(
            description=(
                f"# 📊 Niveau de {membre.display_name}\n"
                f"**Niveau {niveau}** · rang **#{rang}**\n\n"
                f"`{barre_progression(actuel, total)}` {actuel} / {total} XP\n"
                f"XP total : **{xp}**"
            ),
            color=COULEUR,
        )
        embed.set_thumbnail(url=membre.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command()
    async def top(self, ctx):
        """Classement des 10 membres les plus actifs."""
        lignes = self.db.execute(
            "SELECT user_id, xp FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT 10",
            (ctx.guild.id,),
        ).fetchall()

        if not lignes:
            return await ctx.send("Personne n'a encore d'XP, lance la conversation ! 💬")

        medailles = ["🥇", "🥈", "🥉"]
        detail = []
        for i, (user_id, xp) in enumerate(lignes):
            membre = ctx.guild.get_member(user_id)
            nom = membre.display_name if membre else "Ancien membre"
            place = medailles[i] if i < 3 else f"**{i + 1}.**"
            detail.append(f"{place} {nom} · niveau {niveau_depuis_xp(xp)} · {xp} XP")

        embed = discord.Embed(
            description="# 🏆 Classement\nLes membres les plus actifs du serveur.\n\n" + "\n".join(detail),
            color=COULEUR,
        )
        await ctx.send(embed=embed)

    @commands.command(usage="@user <xp>")
    @commands.has_permissions(administrator=True)
    async def setxp(self, ctx, membre: discord.Member, xp: int):
        """(Admin) Définit l'XP d'un membre. Utile pour tester ou corriger."""
        if xp < 0:
            return await ctx.send("❌ L'XP ne peut pas être négatif.", delete_after=8)

        self.set_xp(ctx.guild.id, membre.id, xp)
        niveau = niveau_depuis_xp(xp)
        await self.synchroniser_roles(membre, niveau, retirer=True)
        await ctx.send(f"✅ {membre.mention} a maintenant **{xp} XP** (niveau {niveau}).")

    # ── Gestion des erreurs ──
    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Cette commande est réservée aux admins.", delete_after=8)
        elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
            usage = ctx.command.usage or ""
            await ctx.send(f"❌ Utilisation : `!{ctx.command.name} {usage}`", delete_after=10)
        else:
            traceback.print_exception(type(error), error, error.__traceback__)


async def setup(bot):
    await bot.add_cog(Leveling(bot))