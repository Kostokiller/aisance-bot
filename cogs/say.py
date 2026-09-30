import discord
from discord.ext import commands

ROLE_AUTORISE_SAY = 1551834147113406464


def is_authorized():
    async def predicate(ctx):
        return any(role.id == ROLE_AUTORISE_SAY for role in ctx.author.roles)
    return commands.check(predicate)


class Say(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @is_authorized()
    async def say(self, ctx, *, message: str = None):
        # Récupère l'image jointe au message, si il y en a une
        file = None
        image_url = None

        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            file = await attachment.to_file()
            image_url = f"attachment://{attachment.filename}"

        await ctx.message.delete()

        embed = discord.Embed(
            description=message if message else discord.Embed.Empty,
            color=0x1f8b4c
        )

        if image_url:
            embed.set_image(url=image_url)

        if file:
            await ctx.send(file=file, embed=embed)
        else:
            await ctx.send(embed=embed)

    @say.error
    async def say_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("❌ Tu n'as pas la permission d'utiliser cette commande.", delete_after=5)


async def setup(bot):
    await bot.add_cog(Say(bot))