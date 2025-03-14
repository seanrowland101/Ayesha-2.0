import discord

import asyncpg
import time

from Utilities import Checks, ItemObject, Vars, AcolyteObject, AssociationObject
from Utilities.ItemObject import Weapon
from Utilities.AcolyteObject import Acolyte
from Utilities.AssociationObject import Association


class Player:
    """The Ayesha character object

    Attributes
    ----------
    disc_id : int
        The player's Discord ID
    unique_id : int
        A unique ID for miscellaneous purposes. 
        Use disc_id for a proper identifier
    char_name : int
        The player character's name (set by player, not their Discord username)
    xp : int
        The player's xp points
    level : int
        The player's level
    equipped_item : ItemObject.Weapon
        The weapon object of the item equipped by the player
    acolyte1 : AcolyteObject.Acolyte
        The acolyte object of the acolyte equipped by the player in Slot 1
    acolyte2 : AcolyteObject.Acolyte
        The acolyte object of the acolyte equipped by the player in Slot 2
    assc : AssociationObject.Association
        The association object of the association this player is in
    guild_rank : str
        The rank the player holds in the association they are in
    gold : int
        The player's wealth in gold (general currency)
    occupation : str
        The player's class/occupation role
    location : str
        The location of the player on the map
    pvp_wins : int
        The amount of wins the player has in PvP battles
    pvp_fights : int
        The total amount of PvP battles the player has participated in
    boss_wins : int
        The amount of wins the player has in PvE battles
    boss_fights : int
        The total amount of PvE battles the player has participated in
    rubidics : int
        The player's wealth in rubidics (gacha currency)
    pity_counter : int
        The amount of gacha pulls the player has done since their last 
        legendary weapon or 5-star acolyte
    adventure : int
        The endtime (time.time()) of the player's adventure
    destination : str
        The destination of the player's adventure on the map
    gravitas : int
        The player's wealth in gravitas (alternate currency)
    resources : dict
        A dictionary containing the player's resources
    daily_streak : int
        The amount of days in a row the player has used the `daily` command
    """
    def __init__(self, record : asyncpg.Record):
        """
        Parameters
        ----------
        record : asyncpg.Record
            A record containing information from the players table
        """
        self.disc_id = record['user_id']
        self.unique_id = record['num']
        self.char_name = record['user_name']
        self.xp = record['xp']
        self.level = self.get_level()
        self.equipped_item = record['equipped_item']
        self.helmet = record['helmet']
        self.bodypiece = record['bodypiece']
        self.boots = record['boots']
        self.accessory = record['accessory']
        self.acolyte1 = record['acolyte1']
        self.acolyte2 = record['acolyte2']
        self.assc = record['assc']
        self.guild_rank = record['guild_rank']
        self.gold = record['gold']
        self.occupation = record['occupation']
        self.origin = record['origin']
        self.location = record['loc']
        self.pvp_wins = record['pvpwins']
        self.pvp_fights = record['pvpfights']
        self.boss_wins = record['bosswins']
        self.boss_fights = record['bossfights']
        self.rubidics = record['rubidics']
        self.pity_counter = record['pitycounter']
        self.adventure = record['adventure']
        self.destination = record['destination']
        self.gravitas = record['gravitas']
        self.resources = None
        self.pve_limit = record['pve_limit']

    async def _load_equips(self, conn : asyncpg.Connection):
        """Converts object variables from their IDs into the proper objects.
        Run this upon instantiation or else >:(
        """
        self.equipped_item = await ItemObject.get_weapon_by_id(
            conn, self.equipped_item)
        self.helmet = await ItemObject.get_armor_by_id(conn, self.helmet)
        self.bodypiece = await ItemObject.get_armor_by_id(conn, self.bodypiece)
        self.boots = await ItemObject.get_armor_by_id(conn, self.boots)
        self.accessory = await ItemObject.get_accessory_by_id(
            conn, self.accessory)
        self.acolyte1 = await AcolyteObject.get_acolyte_by_id(
            conn, self.acolyte1)
        self.acolyte2 = await AcolyteObject.get_acolyte_by_id(
            conn, self.acolyte2)
        self.assc = await AssociationObject.get_assc_by_id(conn, self.assc)
        self.resources = dict(await self.get_backpack(conn))

        # Radishes changes expedition time
        on_expedition = self.destination == "EXPEDITION"
        radishes_equipped = "Radishes" in (a.acolyte_name 
            for a in (self.acolyte1, self.acolyte2))
        if on_expedition and radishes_equipped:
            time_bonus = int((time.time() - self.adventure) / 10)
            self.adventure -= time_bonus # Effectively increases length

    def get_level(self, get_next = False) -> int:
        """Returns the player's level.
        Pass get_next as true to also get the xp needed to level up.
        """
        def f(x):
            return int(10 * x**3 + 500)
        
        def g(x):
            return int(1/5 * x**4 + 108500)

        if self.xp <= 540500: # Simpler scaling for first 30 levels
            level = 0
            while (self.xp >= f(level)):
                level += 1
        else:
            level = 31
            while (self.xp >= g(level)):
                level += 1

        level = level - 1 if level > 0 else 0

        if get_next:
            if level >= 30:
                return level, g(level+1) - self.xp
            else:
                return level, f(level+1) - self.xp
        else:
            return level

    async def check_xp_increase(self, conn : asyncpg.Connection, 
            ctx : discord.context, xp : int):
        """Increase the player's xp by a set amount.
        This will also increase the player's equipped acolytes xp by 10% of the 
        player's increase.
        If the xp change results in a level-up for any of these entities, 
        a reward will be given and printed to Discord.        
        """
        old_level = self.level
        self.xp += xp
        psql = """
                UPDATE players
                SET xp = xp + $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, xp, self.disc_id)
        self.level = self.get_level()
        if self.level > old_level: # Level up
            gold = self.level * 500
            rubidics = int(self.level / 30) + 1

            await self.give_gold(conn, gold)
            await self.give_rubidics(conn, rubidics)

            embed = discord.Embed(
                title = f"You have levelled up to level {self.level}!",
                color = Vars.ABLUE)
            embed.add_field(
                name = f"{self.char_name}, you gained some rewards",
                value = f"**Gold:** {gold}\n**Rubidics:** {rubidics}")

            await ctx.respond(embed=embed)

        # Check xp for the equipped acolytes
        a_xp = int(xp / 10)
        if self.acolyte1.acolyte_name is not None:
            await self.acolyte1.check_xp_increase(conn, ctx, a_xp)

        if self.acolyte2.acolyte_name is not None:
            await self.acolyte2.check_xp_increase(conn, ctx, a_xp)

    async def set_char_name(self, conn : asyncpg.Connection, name : str):
        """Sets the player's character name. Limit 32 characters."""
        if len(name) > 32:
            raise Checks.ExcessiveCharacterCount(limit=32)
        
        self.char_name = name

        psql = """
                UPDATE players
                SET user_name = $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, name, self.disc_id)

    async def is_weapon_owner(self, conn : asyncpg.Connection, 
            item_id : int) -> bool:
        """Returns true/false depending on whether the item with the given 
        ID is in this player's inventory.
        """
        psql = """
                SELECT item_id FROM items
                WHERE user_id = $1 AND item_id = $2;
                """
        val = await conn.fetchval(psql, self.disc_id, item_id)

        return val is not None

    async def equip_item(self, conn : asyncpg.Connection, item_id : int):
        """Equips an item on the player."""
        if not await self.is_weapon_owner(conn, item_id):
            raise Checks.NotWeaponOwner

        self.equipped_item = await ItemObject.get_weapon_by_id(conn, item_id)

        psql = """
                UPDATE players 
                SET equipped_item = $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, item_id, self.disc_id)

    async def unequip_item(self, conn: asyncpg.Connection):
        """Unequips the current item from the player."""
        self.equipped_item = Weapon() # Create an empty weapon

        psql = """
                UPDATE players SET equipped_item = NULL WHERE user_id = $1;
                """
        await conn.execute(psql, self.disc_id)

    async def is_armor_owner(self, conn : asyncpg.Connection,
        armor_id : int) -> bool:
        """Returns true/false depending on whether the armor with the given
        ID is this player's inventory.
        """
        psql = """
                SELECT armor_id FROM armor
                WHERE user_id = $1 and armor_id = $2;
                """
        return await conn.fetchval(psql, self.disc_id, armor_id) is not None

    async def equip_armor(self, conn : asyncpg.Connection, armor_id : int):
        """Equips armor to the player. Returns the Armor object."""
        if not await self.is_armor_owner(conn, armor_id):
            raise Checks.NotArmorOwner

        armor = await ItemObject.get_armor_by_id(conn, armor_id)
        if armor.slot == "Helmet":
            self.helmet = armor
            psql = """
                    UPDATE equips
                    SET helmet = $1
                    WHERE user_id = $2;
                    """
        elif armor.slot == "Bodypiece":
            self.bodypiece = armor
            psql = """
                    UPDATE equips
                    SET bodypiece = $1
                    WHERE user_id = $2;
                    """
        elif armor.slot == "Boots":
            self.boots = armor
            psql = """
                    UPDATE equips
                    SET boots = $1
                    WHERE user_id = $2;
                    """
        else:
            raise Checks.InvalidArmorType
        await conn.execute(psql, armor.id, self.disc_id)
        return armor

    async def unequip_armor(self, conn : asyncpg.Connection):
        """Unequips all armor the player is currently wearing."""
        psql = """
                UPDATE equips 
                SET helmet = NULL, bodypiece = NULL, boots = NULL
                WHERE user_id = $1;
                """
        await conn.execute(psql, self.disc_id)

    async def is_accessory_owner(self, conn : asyncpg.Connection, 
            item_id : int) -> bool:
        """Returns true/false depending on whether the accessory with the given 
        ID is in this player's wardrobe.
        """
        psql = """
                SELECT accessory_id FROM accessories
                WHERE user_id = $1 AND accessory_id = $2;
                """
        return await conn.fetchval(psql, self.disc_id, item_id) is not None

    async def equip_accessory(self, conn : asyncpg.Connection, item_id : int):
        """Equips an accessory on the player."""
        if not await self.is_accessory_owner(conn, item_id):
            raise Checks.NotAccessoryOwner

        self.accessory = await ItemObject.get_accessory_by_id(conn, item_id)

        psql = """
                UPDATE equips 
                SET accessory = $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, item_id, self.disc_id)

    async def unequip_accessory(self, conn : asyncpg.Connection):
        """Unequips the accessory the player is currently wearing."""
        psql = """
                UPDATE equips 
                SET accessory = NULL
                WHERE user_id = $1;
                """
        await conn.execute(psql, self.disc_id)

    async def is_acolyte_owner(self, conn : asyncpg.Connection, 
            a_id : int) -> bool:
        """Returns true/false depending on whether the acolyte with the given
        ID is in this player's tavern.
        """
        psql = """
                SELECT acolyte_id FROM acolytes
                WHERE user_id = $1 AND acolyte_id = $2;
                """
        val = await conn.fetchval(self.disc_id, a_id)

        return val is not None

    async def equip_acolyte(self, conn : asyncpg.Connection, 
            acolyte_id : int, slot : int):
        """Equips the acolyte with the given ID to the player.
        slot must be an integer 1 or 2.
        """
        if slot not in (1, 2):
            raise Checks.InvalidAcolyteEquip
            # Check this first because its inexpensive and won't waste time

        if not self.is_acolyte_owner(conn, acolyte_id):
            raise Checks.NotAcolyteOwner

        a = acolyte_id == self.acolyte1.acolyte_id
        b = acolyte_id == self.acolyte2.acolyte_id
        if a or b:
            raise Checks.InvalidAcolyteEquip

        if slot == 1:
            self.acolyte1 = AcolyteObject.get_acolyte_by_id(conn, acolyte_id)
            psql = """
                    UPDATE players
                    SET acolyte1 = $1
                    WHERE user_id = $2;
                    """
        elif slot == 2:
            self.acolyte2 = AcolyteObject.get_acolyte_by_id(conn, acolyte_id)
            psql = """
                    UPDATE players
                    SET acolyte2 = $1
                    WHERE user_id = $2;
                    """
        
        await conn.execute(psql, acolyte_id, self.disc_id)

    async def unequip_acolyte(self, conn : asyncpg.Connection, slot : int):
        """Removes the acolyte at the given slot of the player.
        slot must be an integer 1 or 2.
        """
        if slot == 1:
            self.acolyte1 = Acolyte()
            psql = "UPDATE players SET acolyte1 = NULL WHERE user_id = $1;"
            await conn.execute(psql, self.disc_id)
        elif slot == 2:
            self.acolyte2 = Acolyte()
            psql = "UPDATE players SET acolyte2 = NULL WHERE user_id = $1;"
            await conn.execute(psql, self.disc_id)
        else:
            raise Checks.InvalidAcolyteEquip

    async def join_assc(self, conn : asyncpg.Connection, assc_id : int):
        """Makes the player join the association with the given ID"""
        assc = await AssociationObject.get_assc_by_id(conn, assc_id)
        if assc.is_empty:
            raise Checks.InvalidAssociationID
        if await assc.get_member_count(conn) >= assc.get_member_capacity():
            raise Checks.AssociationAtCapacity

        psql = """
                UPDATE players
                SET assc = $1, guild_rank = 'Member'
                WHERE user_id = $2;
                """
        await conn.execute(psql, assc_id, self.disc_id)

        self.assc = assc

    async def set_association_rank(self, conn : asyncpg.Connection, rank : str):
        """Sets the player's association rank."""
        if rank not in ("Member", "Adept", "Officer"):
            raise Checks.InvalidRankName(rank)
        self.guild_rank = rank
        psql = """
                UPDATE players
                SET guild_rank = $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, rank, self.disc_id)

    async def leave_assc(self, conn : asyncpg.Connection):
        """Makes the player leave their current association."""
        if self.assc.is_empty:
            return

        psql1 = """
                UPDATE players
                SET assc = NULL, guild_rank = NULL
                WHERE user_id = $1;
                """
        psql2 = """
                UPDATE brotherhood_champions
                SET champ1 = NULL
                WHERE champ1 = $1;
                """
        psql3 = """
                UPDATE brotherhood_champions
                SET champ2 = NULL
                WHERE champ2 = $1;
                """
        psql4 = """
                UPDATE brotherhood_champions
                SET champ3 = NULL
                WHERE champ3 = $1;
                """
        psql5 = """
                WITH balance AS (
                    DELETE FROM guild_bank_account
                    WHERE user_id = $1
                    RETURNING account_funds
                )
                SELECT account_funds 
                FROM balance;
                """
        psql6 = """
                UPDATE players
                SET gold = gold + $1
                WHERE user_id = $2;
                """

        await conn.execute(psql1, self.disc_id)
        await conn.execute(psql2, self.disc_id)
        await conn.execute(psql3, self.disc_id)
        await conn.execute(psql4, self.disc_id)
        in_bank = await conn.fetchval(psql5, self.disc_id)
        if in_bank is not None:
            await conn.execute(psql6, in_bank, self.disc_id)

        self.assc = Association()

    async def give_gold(self, conn : asyncpg.Connection, gold : int):
        """Gives the player the passed amount of gold."""
        self.gold += gold

        psql = """
                UPDATE players
                SET gold = gold + $1
                WHERE user_id = $2;
                """

        await conn.execute(psql, gold, self.disc_id)

    async def give_rubidics(self, conn : asyncpg.Connection, rubidics : int):
        """Gives the player the passed amount of rubidics."""
        self.rubidics += rubidics

        psql = """
                UPDATE players
                SET rubidics = rubidics + $1
                WHERE user_id = $2;
                """

        await conn.execute(psql, rubidics, self.disc_id)

    async def give_gravitas(self, conn : asyncpg.Connection, gravitas : int):
        """Gives the player the passed amount of gravitas."""
        if gravitas < 0 and gravitas*-1 > self.gravitas:
            gravitas = self.gravitas * -1

        self.gravitas += gravitas

        psql = """
                UPDATE players
                SET gravitas = gravitas + $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, gravitas, self.disc_id)

    async def give_resource(self, conn : asyncpg.Connection, resource : str, 
            amount : int):
        """Give a resource to the player."""
        try:
            if amount < 0 and amount*-1 > self.resources[resource]:
                raise Checks.NotEnoughResources(resource, 
                    amount*-1 - self.resources[resource], 
                    self.resources[resource])
        except KeyError:
            raise Checks.InvalidResource

        psql = f"""
                UPDATE resources
                SET {resource} = {resource} + $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, amount, self.disc_id)

    async def get_backpack(self, conn : asyncpg.Connection) -> asyncpg.Record:
        """Returns a dict containg the player's resource amounts. Keys are:
        Wheat, Oat, Wood, Reeds, Pine, Moss, Iron, Cacao, Fur, Bone, Silver
        """
        psql = """
                SELECT
                    wheat, oat, wood, reeds, pine, moss, iron, cacao,
                    fur, bone, silver
                FROM resources
                WHERE user_id = $1;
                """
        return await conn.fetchrow(psql, self.disc_id)

    async def set_pity_counter(self, conn : asyncpg.Connection, counter : int):
        """Sets the player's pitycounter."""
        self.pity_counter = counter

        psql = """
                UPDATE players
                SET pitycounter = $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, counter, self.disc_id)

    async def set_occupation(self, conn : asyncpg.Connection, occupation : str):
        """Sets the player's occupation."""
        if occupation not in Vars.OCCUPATIONS:
            raise Checks.InvalidOccupation(occupation)

        self.occupation = occupation
        psql = """
                UPDATE players
                SET occupation = $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, occupation, self.disc_id)

    async def set_origin(self, conn : asyncpg.Connection, origin : str):
        """Sets the player's origin"""
        if origin not in Vars.ORIGINS:
            raise Checks.InvalidOrigin

        self.origin = origin
        psql = """
                UPDATE players
                SET origin = $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, origin, self.disc_id)

    async def set_location(self, conn : asyncpg.Connection, location : str):
        """Sets the player's location"""
        self.location = location

        psql = """
                UPDATE players
                SET loc = $1
                WHERE user_id = $2;
                """
        await conn.execute(psql, location, self.disc_id)

    async def set_adventure(self, conn : asyncpg.Connection, adventure : int,
            destination : str):
        """Sets the player's adventure and destination.

        Adventure should be an integer (time.time()). If travelling, destination
        is the desired destination, and adventure is the time of adventure
        completion.
        If expedition, adventure should be the start time of the adventure and
        destination reads "EXPEDITION"
        """
        self.adventure = adventure
        self.destination = destination

        psql = """
                UPDATE players
                SET adventure = $1, destination = $2
                WHERE user_id = $3;
                """
        await conn.execute(psql, adventure, destination, self.disc_id)

    async def log_pve(self, conn : asyncpg.Connection, victory : bool):
        """Increments the player's boss_fights counter, and boss_wins
        if applicable.
        """
        if victory:
            self.boss_fights += 1
            self.boss_wins += 1
            psql = """
                    UPDATE players
                    SET 
                        bosswins = bosswins + 1,
                        bossfights = bossfights + 1
                    WHERE user_id = $1;
                    """
        else:
            self.boss_fights += 1
            psql = """
                    UPDATE players
                    SET bossfights = bossfights + 1
                    WHERE user_id = $1;
                    """
        await conn.execute(psql, self.disc_id)

    async def log_pvp(self, conn : asyncpg.Connection, victory : bool):
        """Increments the player's pvp_fights counter, and pvp_wins
        if applicable.
        """
        if victory:
            self.pvp_fights += 1
            self.pvp_wins += 1
            psql = """
                    UPDATE players
                    SET 
                        pvpwins = pvpwins + 1,
                        pvpfights = pvpfights + 1
                    WHERE user_id = $1;
                    """
        else:
            self.pvp_fights += 1
            psql = """
                    UPDATE players
                    SET pvpfights = pvpfights + 1
                    WHERE user_id = $1;
                    """
        await conn.execute(psql, self.disc_id)

    async def increment_pve_limit(self, conn : asyncpg.Connection):
        """Increase the player's PVE limit by 1"""
        self.pve_limit += 1
        psql = """
                UPDATE players
                SET pve_limit = pve_limit + 1
                WHERE user_id = $1;
                """
        await conn.execute(psql, self.disc_id)

    def get_attack(self) -> int:
        """Returns the player's attack stat, calculated from all other sources.
        The value returned by this method is 'the final say' on the stat.
        """
        attack = 10 + int(self.level / 2)
        attack += self.equipped_item.attack
        attack += self.acolyte1.get_attack()
        attack += self.acolyte2.get_attack()
        valid_weapons = Vars.OCCUPATIONS[self.occupation]['weapon_bonus']
        if self.equipped_item.type in valid_weapons:
            attack += 20
        attack += Vars.ORIGINS[self.origin]['atk_bonus']
        if self.assc.type == "Brotherhood":
            lvl = self.assc.get_level()
            attack += int(lvl * (lvl + 1) / 4)
        attack += Vars.OCCUPATIONS[self.occupation]['atk_bonus']
        attack = int(attack * 1.1) if self.occupation == "Soldier" else attack
        if self.accessory.prefix == "Demonic":
            attack += Vars.ACCESSORY_BONUS["Demonic"][self.accessory.type]
        # TODO implement comptroller bonus

        return attack

    def get_crit(self) -> int:
        """Returns the player's crit stat, calculated from all other sources.
        The value returned by this method is 'the final say' on the stat.
        """
        crit = 5
        crit += self.equipped_item.crit
        crit += self.acolyte1.get_crit()
        crit += self.acolyte2.get_crit()
        crit += Vars.ORIGINS[self.origin]['crit_bonus']
        if self.assc.type == "Brotherhood":
            crit += self.assc.get_level()
        crit += Vars.OCCUPATIONS[self.occupation]['crit_bonus']
        if self.accessory.prefix == "Flexible":
            crit += Vars.ACCESSORY_BONUS["Flexible"][self.accessory.type]
        # TODO implement comptroller bonus

        return crit

    def get_hp(self) -> int:
        """Returns the player's HP stat, calculated from all other sources.
        The value returned by this method is 'the final say' on the stat.
        """
        hp = 500 + self.level * 3
        hp += self.acolyte1.get_hp()
        hp += self.acolyte2.get_hp()
        hp += Vars.ORIGINS[self.origin]['hp_bonus']
        hp += Vars.OCCUPATIONS[self.occupation]['hp_bonus']
        if self.accessory.prefix == "Thick":
            hp += Vars.ACCESSORY_BONUS["Thick"][self.accessory.type]
        # TODO implement comptroller bonus

        return hp

    def get_defense(self) -> int:
        """Returns the player's DEF stat, calculated from all other sources.
        The value returned by this method is 'the final say` on the stat.
        """
        base = self.helmet.defense + self.bodypiece.defense + self.boots.defense
        if self.occupation == "Leatherworker":
            if not self.helmet.is_empty:
                base += 3
            if not self.bodypiece.is_empty:
                base += 3
            if not self.boots.is_empty:
                base += 3
        if self.accessory.prefix == "Strong":
            base += Vars.ACCESSORY_BONUS["Strong"][self.accessory.type]
        return base


async def get_player_by_id(conn : asyncpg.Connection, user_id : int) -> Player:
    """Return a player object of the player with the given Discord ID."""
    psql = """
            SELECT 
                players.num,
                players.user_id,
                players.user_name,
                players.xp,
                players.equipped_item,
                players.acolyte1,
                players.acolyte2,
                players.assc,
                players.guild_rank,
                players.gold,
                players.occupation,
                players.origin,
                players.loc,
                players.pvpwins,
                players.pvpfights,
                players.bosswins,
                players.bossfights,
                players.rubidics,
                players.pitycounter,
                players.adventure,
                players.destination,
                players.gravitas,
                players.pve_limit,
                equips.helmet,
                equips.bodypiece,
                equips.boots,
                equips.accessory
            FROM players
            INNER JOIN equips
                ON players.user_id = equips.user_id
            WHERE players.user_id = $1;
            """
    
    player_record = await conn.fetchrow(psql, user_id)

    if player_record is None:
        raise Checks.PlayerHasNoChar

    player = Player(player_record)
    await player._load_equips(conn)

    return player

async def create_character(conn : asyncpg.Connection, user_id : int, 
        name : str) -> Player:
    """Creates and returns a profile for the user with the given Discord ID."""
    psql1 = "INSERT INTO players (user_id, user_name) VALUES ($1, $2);"
    psql2 = "INSERT INTO resources (user_id) VALUES ($1);"
    psql3 = "INSERT INTO strategy (user_id) VALUES ($1);"
    psql4 = "INSERT INTO equips (user_id) VALUES ($1);"
    await conn.execute(psql1, user_id, name)
    await conn.execute(psql2, user_id)
    await conn.execute(psql3, user_id)
    await conn.execute(psql4, user_id)

    await ItemObject.create_weapon(
        conn, user_id, "Common", attack=20, crit=0, weapon_name="Wooden Spear", 
        weapon_type="Spear")

    return await get_player_by_id(conn, user_id)

async def get_player_by_num(conn : asyncpg.Connection, num : int) -> Player:
    """Returns the player object of the person with the given num 
    (unique, non-Discord ID). Raises Checks.NonexistentPlayer if there is no
    player with this num.
    """
    psql = """
            SELECT user_id
            FROM players
            WHERE num = $1;
            """
    user_id = await conn.fetchval(psql, num)
    if user_id is None:
        raise Checks.NonexistentPlayer
    return await get_player_by_id(conn, user_id)

async def get_player_count(conn : asyncpg.Connection):
    """Return an integer of the amount of players in the database."""
    psql = """
            SELECT COUNT(*)
            FROM players;
            """
    return await conn.fetchval(psql)

async def get_comptroller(conn : asyncpg.Connection):
    """Returns a record containing the current comptrollers's ID and username.
    Keys: officeholder, user_name
    """
    psql1 = """
            SELECT officeholders.officeholder, players.user_name
            FROM officeholders
            INNER JOIN players
                ON officeholders.officeholder = players.user_id
            WHERE office = 'Comptroller'
            ORDER BY id DESC
            LIMIT 1;
            """
    return await conn.fetchrow(psql1)

async def get_mayor(conn : asyncpg.Connection):
    """Returns a record containing the current mayor's ID and username.
    Keys: officeholder, user_name
    """
    psql1 = """
            SELECT officeholders.officeholder, players.user_name
            FROM officeholders
            INNER JOIN players
                ON officeholders.officeholder = players.user_id
            WHERE office = 'Mayor'
            ORDER BY id DESC
            LIMIT 1;
            """
    return await conn.fetchrow(psql1)