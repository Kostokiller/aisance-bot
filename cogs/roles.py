import os

import discord
from discord.ext import commands

# ─────────────────────────────────────────────
# IDs des rôles
# ─────────────────────────────────────────────
ROLE_PLUS18 = 1554794249780858900
ROLE_MOINS18 = 1554794894717886485
ROLE_HOMME = 1554794895737098331
ROLE_FEMME = 1554794895980367872
ROLE_DM_OUVERT = 1554794896848850964
ROLE_DM_FERME = 1554794897444311110
ROLE_DM_DEMANDE = 1554794898383962195
ROLE_MONEY_LOVER = 1554794900132728862
ROLE_CRYPTO_ADDICT = 1554795290631086091
ROLE_NIGHT_OWL = 1554795292124123156
ROLE_GRIND_MODE = 1554795292166070317
ROLE_LUXE_ADDICT = 1554795292673581086

# Groupes de rôles
GROUPE_AGE = [ROLE_PLUS18, ROLE_MOINS18]
GROUPE_GENRE = [ROLE_HOMME, ROLE_FEMME]
GROUPE_DM = [ROLE_DM_OUVERT, ROLE_DM_FERME, ROLE_DM_DEMANDE]
GROUPE_VIBE = [ROLE_MONEY_LOVER, ROLE_CRYPTO_ADDICT, ROLE_NIGHT_OWL, ROLE_GRIND_MODE, ROLE_LUXE_ADDICT]

# Bannière optionnelle : si le fichier existe, elle est ajoutée au message
BANNIERE_PATH = "assets/Roles.png"


# ─────────────────────────────────────────────
# Fonctions utilitaires
# ─────────────────────────────────────────────
async def appliquer_choix_exclusif(interaction, groupe_ids, role_choisi_id):
    """Un seul rôle possible dans le groupe : retire les autres, ajoute celui choisi."""
    guild = interaction.guild
    membre = interaction.user

    for role_id in groupe_ids:
        role = guild.get_role(role_id)
        if role and role in membre.roles and role_id != role_choisi_id:
            await membre.remove_roles(role)

    role_a_ajouter = guild.get_role(role_choisi_id)
    if role_a_ajouter and role_a_ajouter not in membre.roles:
        await membre.add_roles(role_a_ajouter)


async def appliquer_choix_multiple(interaction, groupe_ids, roles_choisis_ids):
    """Plusieurs rôles possibles : ajoute les choisis, retire les décochés."""
    guild = interaction.guild
    membre = interaction.user

    for role_id in groupe_ids:
        role = guild.get_role(role_id)
        if role is None:
            continue

        if role_id in roles_choisis_ids:
            if role not in membre.roles:
                await membre.add_roles(role)
        else:
            if role in membre.roles:
                await membre.remove_roles(role)


# ─────────────────────────────────────────────
# Menus déroulants
# ─────────────────────────────────────────────
class SelectAge(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="+18", value=str(ROLE_PLUS18), emoji="🔞"),
            discord.SelectOption(label="-18", value=str(ROLE_MOINS18), emoji="🍼"),
        ]
        super().__init__(placeholder="Choisis ton âge", options=options, custom_id="select_age")

    async def callback(self, interaction: discord.Interaction):
        role_id = int(self.values[0])
        await appliquer_choix_exclusif(interaction, GROUPE_AGE, role_id)
        await interaction.response.send_message("✅ Rôle âge mis à jour.", ephemeral=True)


class SelectGenre(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Homme", value=str(ROLE_HOMME), emoji="♂️"),
            discord.SelectOption(label="Femme", value=str(ROLE_FEMME), emoji="♀️"),
        ]
        super().__init__(placeholder="Choisis ton genre", options=options, custom_id="select_genre")

    async def callback(self, interaction: discord.Interaction):
        role_id = int(self.values[0])
        await appliquer_choix_exclusif(interaction, GROUPE_GENRE, role_id)
        await interaction.response.send_message("✅ Rôle genre mis à jour.", ephemeral=True)


class SelectDM(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="DM ouvert", value=str(ROLE_DM_OUVERT), emoji="🟢"),
            discord.SelectOption(label="DM fermé", value=str(ROLE_DM_FERME), emoji="🔴"),
            discord.SelectOption(label="DM sur demande", value=str(ROLE_DM_DEMANDE), emoji="🟡"),
        ]
        super().__init__(placeholder="Ta préférence DM", options=options, custom_id="select_dm")

    async def callback(self, interaction: discord.Interaction):
        role_id = int(self.values[0])
        await appliquer_choix_exclusif(interaction, GROUPE_DM, role_id)
        await interaction.response.send_message("✅ Préférence DM mise à jour.", ephemeral=True)


class SelectVibe(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Money lover", value=str(ROLE_MONEY_LOVER), emoji="💰"),
            discord.SelectOption(label="Crypto addict", value=str(ROLE_CRYPTO_ADDICT), emoji="🪙"),
            discord.SelectOption(label="Night owl", value=str(ROLE_NIGHT_OWL), emoji="🦉"),
            discord.SelectOption(label="Grind mode", value=str(ROLE_GRIND_MODE), emoji="📈"),
            discord.SelectOption(label="Luxe addict", value=str(ROLE_LUXE_ADDICT), emoji="🥂"),
        ]
        super().__init__(
            placeholder="Ta vibe (plusieurs choix possibles)",
            options=options,
            custom_id="select_vibe",
            min_values=0,
            max_values=len(options),
        )

    async def callback(self, interaction: discord.Interaction):
        roles_choisis_ids = [int(v) for v in self.values]
        await appliquer_choix_multiple(interaction, GROUPE_VIBE, roles_choisis_ids)
        await interaction.response.send_message("✅ Vibe(s) mise(s) à jour.", ephemeral=True)


class RolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SelectAge())
        self.add_item(SelectGenre())
        self.add_item(SelectDM())
        self.add_item(SelectVibe())


# ─────────────────────────────────────────────
# Cog + commande
# ─────────────────────────────────────────────
class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Réactive les menus après un redémarrage du bot
        self.bot.add_view(RolesView())

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def post_roles(self, ctx):
        embed = discord.Embed(
            description=(
                "# 🎭 Choisis tes rôles\n"
                "Personnalise ton profil sur **@Aisance** en quelques clics. "
                "Tu peux modifier tes choix à tout moment.\n\n"

                "## 🔞 Âge\n"
                "Permet de savoir qui est majeur ou non sur le serveur.\n\n"

                "## ⚧ Genre\n"
                "Optionnel, juste pour se situer entre membres.\n\n"

                "## 💬 Préférence DM\n"
                "Indique aux autres si tu es ouvert aux messages privés, "
                "fermé, ou seulement sur demande.\n\n"

                "## ✨ Ta vibe\n"
                "Plusieurs choix possibles, choisis ce qui te ressemble :\n"
                "• 💰 **Money lover** → toujours un œil sur tes finances\n"
                "• 🪙 **Crypto addict** → tu suis les marchés et les projets\n"
                "• 🦉 **Night owl** → plus actif la nuit, présent en vocal tard\n"
                "• 📈 **Grind mode** → à fond sur un projet ou un side hustle\n"
                "• 🥂 **Luxe addict** → t'aimes le beau, le raffiné, kiffer la vie\n\n"

                "## 👇 À toi de jouer\n"
                "Utilise les menus juste en dessous."
            ),
            color=0x1f8b4c,
        )

        # Si assets/Roles.png existe, on l'ajoute en bannière
        if os.path.exists(BANNIERE_PATH):
            fichier = discord.File(BANNIERE_PATH, filename="Roles.png")
            embed.set_image(url="attachment://Roles.png")
            await ctx.send(embed=embed, file=fichier, view=RolesView())
        else:
            await ctx.send(embed=embed, view=RolesView())


async def setup(bot):
    await bot.add_cog(Roles(bot))