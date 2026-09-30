from discord.ext import commands


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def lock(self, ctx, role_id: int):
        role = ctx.guild.get_role(role_id)
        if role is None:
            await ctx.send("❌ Rôle introuvable, vérifie l'ID.")
            return

        await ctx.channel.set_permissions(role, view_channel=True, send_messages=False)
        await ctx.send(f"🔒 **{ctx.channel.name}** verrouillé pour **{role.name}** : lecture seule.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def unlock(self, ctx, role_id: int):
        role = ctx.guild.get_role(role_id)
        if role is None:
            await ctx.send("❌ Rôle introuvable, vérifie l'ID.")
            return

        await ctx.channel.set_permissions(role, view_channel=True, send_messages=True)
        await ctx.send(f"🔓 **{ctx.channel.name}** déverrouillé pour **{role.name}** : lecture + écriture.")


async def setup(bot):
    await bot.add_cog(Moderation(bot))