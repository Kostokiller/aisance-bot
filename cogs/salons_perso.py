import os
import sqlite3

import discord
from discord.ext import commands

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
SALON_CREATION_ID = 1554828509317431296  # vocal "créer ton channel"
SALON_PANNEAU_ID = 1554791640919707688   # salon texte où le bot envoie le message de personnalisation

DB_PATH = "data/salons.db"
COULEUR = 0x1f8b4c


# ─────────────────────────────────────────────
# Fenêtres (modals) pour saisir le nom / la limite
# ─────────────────────────────────────────────
class NomModal(discord.ui.Modal, title="Renommer ton salon"):
    def __init__(self, salon: discord.VoiceChannel):
        super().__init__()
        self.salon = salon
        self.nom = discord.ui.TextInput(
            label="Nouveau nom", default=salon.name, min_length=1, max_length=50
        )
        self.add_item(self.nom)

    async def on_submit(self, interaction: discord.Interaction):
        # defer = on répond tout de suite à Discord, car renommer peut être lent (rate limit)
        await interaction.response.defer(ephemeral=True)
        try:
            await self.salon.edit(name=self.nom.value)
        except discord.HTTPException:
            return await interaction.followup.send("❌ Impossible de renommer le salon.", ephemeral=True)
        await interaction.followup.send(f"✅ Salon renommé en **{self.nom.value}**.", ephemeral=True)


class LimiteModal(discord.ui.Modal, title="Limite de personnes"):
    def __init__(self, salon: discord.VoiceChannel):
        super().__init__()
        self.salon = salon
        self.limite = discord.ui.TextInput(
            label="Nombre max (0 = illimité, max 99)",
            default=str(salon.user_limit),
            min_length=1,
            max_length=2,
        )
        self.add_item(self.limite)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.limite.value.isdigit():
            return await interaction.response.send_message("❌ Entre un nombre (ex : 5).", ephemeral=True)

        n = int(self.limite.value)
        await interaction.response.defer(ephemeral=True)
        try:
            await self.salon.edit(user_limit=n)
        except discord.HTTPException:
            return await interaction.followup.send("❌ Impossible de changer la limite.", ephemeral=True)

        texte = "illimitée" if n == 0 else f"**{n}** personne(s)"
        await interaction.followup.send(f"✅ Limite : {texte}.", ephemeral=True)


# ─────────────────────────────────────────────
# Boutons du message de personnalisation
# ─────────────────────────────────────────────
class PanneauView(discord.ui.View):
    def __init__(self, salon: discord.VoiceChannel, proprietaire: discord.Member):
        super().__init__(timeout=None)
        self.salon = salon
        self.proprietaire = proprietaire

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.proprietaire.id:
            await interaction.response.send_message("❌ Ce salon n'est pas à toi.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Nom", emoji="✏️", style=discord.ButtonStyle.primary)
    async def bouton_nom(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NomModal(self.salon))

    @discord.ui.button(label="Limite", emoji="👥", style=discord.ButtonStyle.primary)
    async def bouton_limite(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LimiteModal(self.salon))

    @discord.ui.button(label="Cacher le salon", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def bouton_visibilite(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = self.salon.guild.default_role  # @everyone
        droits = self.salon.overwrites_for(role)
        etait_visible = droits.view_channel is not False
        droits.view_channel = False if etait_visible else None

        await interaction.response.defer()
        try:
            await self.salon.set_permissions(role, overwrite=droits)
        except discord.HTTPException:
            return await interaction.followup.send(
                "❌ Je n'ai pas pu changer la visibilité (permission manquante ?).", ephemeral=True
            )

        button.label = "Rendre visible" if etait_visible else "Cacher le salon"
        await interaction.edit_original_response(view=self)
        await interaction.followup.send(
            "🔒 Ton salon est maintenant **caché**." if etait_visible else "🔓 Ton salon est de nouveau **visible**.",
            ephemeral=True,
        )


# ─────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────
class SalonsPerso(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.salons = {}  # id du salon -> (id du proprio, message du panneau ou None)

        os.makedirs("data", exist_ok=True)
        self.db = sqlite3.connect(DB_PATH)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS salons ("
            "channel_id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL)"
        )
        self.db.commit()

    async def cog_unload(self):
        self.db.close()

    # ── Nettoyage au démarrage (si le bot a redémarré pendant que des salons existaient) ──
    @commands.Cog.listener()
    async def on_ready(self):
        lignes = self.db.execute("SELECT channel_id, owner_id FROM salons").fetchall()
        for channel_id, owner_id in lignes:
            if channel_id in self.salons:
                continue
            salon = self.bot.get_channel(channel_id)
            if salon is None:
                self.db.execute("DELETE FROM salons WHERE channel_id = ?", (channel_id,))
                self.db.commit()
            elif not salon.members:
                await self.supprimer(salon)
            else:
                self.salons[channel_id] = (owner_id, None)  # sera supprimé quand il sera vide

    # ── Suppression d'un salon perso ──
    async def supprimer(self, salon: discord.VoiceChannel):
        _, message = self.salons.pop(salon.id, (None, None))
        self.db.execute("DELETE FROM salons WHERE channel_id = ?", (salon.id,))
        self.db.commit()

        if message:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        try:
            await salon.delete(reason="Salon perso vide")
        except discord.HTTPException:
            pass

    # ── Création d'un salon perso ──
    async def creer_salon(self, membre: discord.Member, salon_creation: discord.VoiceChannel):
        # Il a déjà un salon ? On le remet dedans au lieu d'en créer un deuxième.
        for channel_id, (owner_id, _) in self.salons.items():
            if owner_id == membre.id:
                existant = self.bot.get_channel(channel_id)
                if existant:
                    try:
                        await membre.move_to(existant)
                    except discord.HTTPException:
                        pass
                    return

        # On copie les permissions du salon "créer ton channel" + le proprio peut voir/rejoindre
        droits = dict(salon_creation.overwrites)
        droits[membre] = discord.PermissionOverwrite(view_channel=True, connect=True)

        try:
            salon = await membre.guild.create_voice_channel(
                name=f"Salon de {membre.display_name}"[:100],
                category=salon_creation.category,
                overwrites=droits,
                reason=f"Salon perso de {membre}",
            )
        except discord.HTTPException as e:
            print(f"[SalonsPerso] Impossible de créer le salon : {e}")
            return

        self.salons[salon.id] = (membre.id, None)
        self.db.execute(
            "INSERT OR REPLACE INTO salons (channel_id, owner_id) VALUES (?, ?)", (salon.id, membre.id)
        )
        self.db.commit()

        try:
            await membre.move_to(salon)
        except discord.HTTPException:
            # le membre s'est déconnecté entre-temps
            return await self.supprimer(salon)

        # Message de personnalisation
        message = None
        panneau = self.bot.get_channel(SALON_PANNEAU_ID)
        if panneau:
            embed = discord.Embed(
                description=(
                    "# 🎛️ Personnalise ton salon\n"
                    f"Ton salon vocal {salon.mention} est prêt !\n"
                    "Utilise les boutons ci-dessous pour :\n"
                    "✏️ choisir son **nom**\n"
                    "👥 fixer une **limite** de personnes\n"
                    "👁️ le rendre **visible** ou **caché**\n\n"
                    "*Il sera supprimé automatiquement quand il sera vide.*"
                ),
                color=COULEUR,
            )
            try:
                message = await panneau.send(
                    content=membre.mention, embed=embed, view=PanneauView(salon, membre)
                )
            except discord.HTTPException as e:
                print(f"[SalonsPerso] Impossible d'envoyer le panneau : {e}")

        # Si le salon a déjà été supprimé pendant ce temps (membre parti très vite)
        if salon.id in self.salons:
            self.salons[salon.id] = (membre.id, message)
        elif message:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

    # ── Écoute des salons vocaux ──
    @commands.Cog.listener()
    async def on_voice_state_update(self, membre, avant, apres):
        if avant.channel == apres.channel:
            return  # simple changement (micro coupé, etc.)

        # 1) Quelqu'un rejoint "créer ton channel"
        if apres.channel and apres.channel.id == SALON_CREATION_ID:
            await self.creer_salon(membre, apres.channel)

        # 2) Quelqu'un quitte un salon perso : s'il est vide, on le supprime
        if avant.channel and avant.channel.id in self.salons and not avant.channel.members:
            await self.supprimer(avant.channel)


async def setup(bot):
    await bot.add_cog(SalonsPerso(bot))