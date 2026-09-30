import asyncio

import discord
from discord.ext import commands

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
CATEGORIE_TICKETS_ID = 1554821847068180592   # catégorie où les tickets apparaissent
ROLE_STAFF_TICKETS_ID = 1554793672888029235  # seul rôle (avec le créateur) à voir les tickets
LOGS_CHANNEL_ID = 1554797148288323636        # salon où sont envoyés les logs de tickets
COULEUR = 0x1f8b4c
COULEUR_FERMETURE = 0xc0392b

# Les 5 catégories : clé -> (label, emoji, description courte, texte d'accueil dans le ticket)
CATEGORIES = {
    "questions": (
        "Questions", "❓",
        "Une question sur le serveur ou le projet",
        "Pose ta question ci-dessous, on te répond dès que possible.",
    ),
    "support": (
        "Support", "🛠️",
        "Un souci technique ou un problème sur le serveur",
        "Décris ton problème le plus précisément possible (captures d'écran bienvenues).",
    ),
    "plainte": (
        "Plainte", "🚨",
        "Signaler un membre ou un problème de comportement",
        "Explique la situation calmement, avec des preuves si tu en as (captures, liens de messages).",
    ),
    "formation": (
        "Formation", "🎓",
        "Des questions sur la formation",
        "Dis-nous ce que tu veux savoir sur la formation, on est là pour t'expliquer.",
    ),
    "autre": (
        "Autre", "📩",
        "Tout ce qui ne rentre pas dans les autres cases",
        "Explique-nous ta demande, on t'aidera au mieux.",
    ),
}


# ─────────────────────────────────────────────
# Fonctions utilitaires
# ─────────────────────────────────────────────
def get_owner_id(channel):
    """Retrouve l'ID du créateur du ticket grâce au topic du salon (ex: 'ticket_owner:123')."""
    if channel.topic and channel.topic.startswith("ticket_owner:"):
        try:
            return int(channel.topic.split(":")[1])
        except ValueError:
            return None
    return None


async def envoyer_log(guild, embed):
    """Envoie un embed dans le salon de logs (sans planter si le salon est introuvable)."""
    salon = guild.get_channel(LOGS_CHANNEL_ID)
    if salon is None:
        return
    try:
        await salon.send(embed=embed)
    except discord.HTTPException:
        pass


def formater_duree(delta):
    """Transforme une durée en texte lisible (ex: '2h 15min')."""
    total = int(delta.total_seconds())
    jours, reste = divmod(total, 86400)
    heures, reste = divmod(reste, 3600)
    minutes, secondes = divmod(reste, 60)
    if jours:
        return f"{jours}j {heures}h {minutes}min"
    if heures:
        return f"{heures}h {minutes}min"
    if minutes:
        return f"{minutes}min {secondes}s"
    return f"{secondes}s"


def trouver_ticket_ouvert(categorie, membre):
    """Renvoie le salon du ticket ouvert par ce membre, ou None."""
    for salon in categorie.text_channels:
        if get_owner_id(salon) == membre.id:
            return salon
    return None


# ─────────────────────────────────────────────
# Bouton de fermeture (dans le ticket)
# ─────────────────────────────────────────────
class ConfirmerFermeture(discord.ui.View):
    """Petite confirmation pour éviter de fermer un ticket par erreur."""

    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="Oui, fermer", style=discord.ButtonStyle.danger, emoji="🔒")
    async def confirmer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🔒 Ticket fermé, suppression dans 5 secondes...", view=None)

        # ── Log de fermeture ──
        salon = interaction.channel
        maintenant = discord.utils.utcnow()
        owner_id = get_owner_id(salon)

        embed_log = discord.Embed(title="🔒 Ticket fermé", color=COULEUR_FERMETURE, timestamp=maintenant)
        embed_log.add_field(name="Ticket", value=f"`#{salon.name}`", inline=True)
        embed_log.add_field(name="Créé par", value=f"<@{owner_id}>" if owner_id else "Inconnu", inline=True)
        embed_log.add_field(name="Fermé par", value=interaction.user.mention, inline=True)
        embed_log.add_field(name="Ouvert le", value=discord.utils.format_dt(salon.created_at, "F"), inline=True)
        embed_log.add_field(name="Fermé le", value=discord.utils.format_dt(maintenant, "F"), inline=True)
        embed_log.add_field(name="Durée", value=formater_duree(maintenant - salon.created_at), inline=True)
        await envoyer_log(interaction.guild, embed_log)

        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket fermé par {interaction.user}")

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def annuler(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Fermeture annulée.", view=None)


class FermerTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_fermer")
    async def fermer(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id = get_owner_id(interaction.channel)
        role_staff = interaction.guild.get_role(ROLE_STAFF_TICKETS_ID)

        # Seuls le créateur et le staff peuvent fermer
        est_owner = interaction.user.id == owner_id
        est_staff = role_staff in interaction.user.roles if role_staff else False

        if not (est_owner or est_staff):
            await interaction.response.send_message("❌ Tu ne peux pas fermer ce ticket.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Tu veux vraiment fermer ce ticket ? Le salon sera supprimé.",
            view=ConfirmerFermeture(),
            ephemeral=True,
        )


# ─────────────────────────────────────────────
# Menu de création (dans le salon #tickets)
# ─────────────────────────────────────────────
class SelectTicket(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=cle, emoji=emoji, description=desc)
            for cle, (label, emoji, desc, _) in CATEGORIES.items()
        ]
        super().__init__(
            placeholder="Choisis le type de ticket",
            options=options,
            custom_id="select_ticket",
        )

    async def callback(self, interaction: discord.Interaction):
        # On répond vite (la création du salon peut prendre quelques secondes)
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        membre = interaction.user
        cle = self.values[0]
        label, emoji, _, accueil = CATEGORIES[cle]

        categorie = guild.get_channel(CATEGORIE_TICKETS_ID)
        role_staff = guild.get_role(ROLE_STAFF_TICKETS_ID)

        if categorie is None or role_staff is None:
            await interaction.followup.send("❌ Config du système de tickets invalide, préviens le staff.", ephemeral=True)
            return

        # Un seul ticket ouvert par membre
        existant = trouver_ticket_ouvert(categorie, membre)
        if existant:
            await interaction.followup.send(f"❌ Tu as déjà un ticket ouvert : {existant.mention}", ephemeral=True)
            return

        # Permissions : invisible pour tous, visible pour le créateur + le staff + le bot
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            membre: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True,
            ),
            role_staff: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True, manage_messages=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, read_message_history=True,
            ),
        }

        salon = await guild.create_text_channel(
            name=f"{cle}-{membre.name}",
            category=categorie,
            overwrites=overwrites,
            topic=f"ticket_owner:{membre.id}",
            reason=f"Ticket {label} ouvert par {membre}",
        )

        embed = discord.Embed(
            description=(
                f"# {emoji} Ticket {label}\n"
                f"Salut {membre.mention} 👋\n\n"
                f"{accueil}\n\n"
                "Un membre du staff va te répondre dès que possible.\n"
                "Quand c'est réglé, clique sur **Fermer le ticket**."
            ),
            color=COULEUR,
        )
        await salon.send(
            content=f"{membre.mention} {role_staff.mention}",
            embed=embed,
            view=FermerTicketView(),
        )

        await interaction.followup.send(f"✅ Ton ticket est prêt : {salon.mention}", ephemeral=True)

        # ── Log d'ouverture ──
        embed_log = discord.Embed(title="🎫 Ticket ouvert", color=COULEUR, timestamp=discord.utils.utcnow())
        embed_log.add_field(name="Ticket", value=salon.mention, inline=True)
        embed_log.add_field(name="Catégorie", value=f"{emoji} {label}", inline=True)
        embed_log.add_field(name="Ouvert par", value=membre.mention, inline=True)
        await envoyer_log(guild, embed_log)

        # On remet le menu à zéro (sinon la dernière option reste affichée comme choisie)
        try:
            await interaction.message.edit(view=TicketPanelView())
        except discord.HTTPException:
            pass


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SelectTicket())


# ─────────────────────────────────────────────
# Cog + commande
# ─────────────────────────────────────────────
class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Réactive le menu et le bouton après un redémarrage du bot
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(FermerTicketView())

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def post_tickets(self, ctx):
        embed = discord.Embed(
            description=(
                "# 🎫 Besoin d'aide ?\n"
                "Ouvre un ticket privé : seuls toi et le staff pourrez le voir.\n\n"

                "## 📂 Choisis une catégorie\n"
                "• ❓ **Questions** → une question sur le serveur ou le projet\n"
                "• 🛠️ **Support** → un souci technique ou un problème\n"
                "• 🚨 **Plainte** → signaler un membre ou un comportement\n"
                "• 🎓 **Formation** → tout savoir sur la formation\n"
                "• 📩 **Autre** → tout le reste\n\n"

                "## 👇 À toi de jouer\n"
                "Sélectionne la catégorie dans le menu juste en dessous.\n"
                "*Un seul ticket ouvert à la fois par personne.*"
            ),
            color=COULEUR,
        )
        await ctx.send(embed=embed, view=TicketPanelView())


async def setup(bot):
    await bot.add_cog(Tickets(bot))