import discord
from discord.ext import commands

ROLE_MEMBRE_ID = 1554793779687333909
CHANNEL_INFORMATIONS_ID = 1554791396421148672
CHANNEL_ROLES_ID = 1554791416839012392

ROLES_AUTO = [
    ROLE_MEMBRE_ID,
    1554793782757691464,
    1554794809351217195,
    1554794899432411206,
]


class ReglementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ J'accepte le règlement", style=discord.ButtonStyle.green, custom_id="accept_rules")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        membre = interaction.user

        role_membre = guild.get_role(ROLE_MEMBRE_ID)
        if role_membre in membre.roles:
            await interaction.response.send_message("Tu as déjà le rôle Membre ✅", ephemeral=True)
            return

        roles_a_ajouter = []
        for role_id in ROLES_AUTO:
            role = guild.get_role(role_id)
            if role and role not in membre.roles:
                roles_a_ajouter.append(role)

        await membre.add_roles(*roles_a_ajouter)

        await interaction.response.send_message(
            f"Bienvenue ! Le rôle **Membre** t'a été attribué 🎉\n\n"
            f"Fais un tour dans <#{CHANNEL_INFORMATIONS_ID}> et <#{CHANNEL_ROLES_ID}> avant de commencer !",
            ephemeral=True
        )


class Reglement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(ReglementView())

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def post_reglement(self, ctx):
        embed = discord.Embed(
            title="✦ RÈGLEMENT ✦",
            description=(
                "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n"
                "*Ces quelques règles servent à garder un espace sain, respectueux et agréable pour tout le monde.*\n\n"
                "**🤝 Respect avant tout**\n"
                "Aucune tolérance pour le harcèlement, les insultes, le racisme, l'homophobie ou toute forme de discrimination.\n\n"
                "**💬 No hate, no drama**\n"
                "Les débats sont les bienvenus, mais restez respectueux même en désaccord.\n\n"
                "**🚫 Contenu interdit**\n"
                "Pas de contenu NSFW, violent, illégal, ou choquant. Pas de spam ni de pub non autorisée.\n\n"
                "**⚠️ Pas d'arnaque, pas de fake**\n"
                "Aucune tentative d'arnaque, de phishing, ou d'usurpation d'identité tolérée.\n\n"
                "**🔒 Respect de la vie privée**\n"
                "Pas de partage d'informations personnelles sur d'autres membres sans accord.\n\n"
                "**👮 Le staff a le dernier mot**\n"
                "Une sanction non justifiée à tes yeux ? Ouvre un ticket, pas de clash public."
            ),
            color=0x1f8b4c
        )

        await ctx.send(embed=embed)

        embed2 = discord.Embed(
            description="**En cliquant ci-dessous, tu acceptes ces règles.**",
            color=0x1f8b4c
        )
        embed2.set_image(url="attachment://Reglement.png")

        reglement_file = discord.File("assets/Reglement.png", filename="Reglement.png")
        await ctx.send(file=reglement_file, embed=embed2, view=ReglementView())


async def setup(bot):
    await bot.add_cog(Reglement(bot))