import discord
from discord.ext import commands

CHANNEL_REGLES_ID = 1554791216791687189
CHANNEL_BIENVENUE_ID = 1554791047198933052


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        channel = self.bot.get_channel(CHANNEL_BIENVENUE_ID)

        embed = discord.Embed(
            description=f"Bienvenue {member.mention} sur **@Aisance** !\n\nVa jeter un œil au règlement dans <#{CHANNEL_REGLES_ID}> pour débloquer l'accès complet au serveur.",
            color=0x1f8b4c
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_image(url="attachment://Bienvenue.png")

        file = discord.File("assets/Bienvenue.png", filename="Bienvenue.png")

        await channel.send(file=file, embed=embed)


async def setup(bot):
    await bot.add_cog(Welcome(bot))