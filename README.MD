# Grand Line Sentinel Bot

Telegram RPG bot for One Piece-style gameplay.

## Version 1.2.0

This release keeps the complete `grandlineG_bot6` base and adds the latest feature and reliability updates.

### Fishing

- `/fish`, `/fishing`, `/fishes`, and `/sell_fish`
- Seven fish types with bounty rewards
- Wooden, steel, diamond, and mythical rods and bait
- Durability, shop purchases, fish inventory, individual selling, and Sell All
- Fishing shop captions show each rod/bait price, uses, and XP bonus; purchases require confirmation
- Fishing rewards normal player XP
- Owner-only `/setfish` sticker setup

### Mines gambling

- Start with `/mines [amount]`, for example `/mines 100K`
- The board has 25 tiles and 5 hidden mines
- Each safe tile increases the potential cash-out multiplier
- Tap **Cash Out** to collect the current payout
- Hitting a mine loses the placed bet
- Ending a game also forfeits the placed bet
- Owner can reply to an active board with `/trackmines` to reveal mine locations

### Custom character rarities

- Owner creates a rarity with `/addrarity [name]`, for example `/addrarity Celestial`
- Admins can view available rarities with `/rarities`
- Owner/admin can assign it with `/edit [id] rarity CELESTIAL`
- Owner can add characters with `/celestialadd` and delete them with `/celestialdelete [id]`
- Owner can remove a custom rarity with `/deleterarity [name]`
- Owner can configure winning bounty with `/setrarityreward [rarity] [minimum] [maximum]`
- Custom rarity definitions are saved in `data/rarities.json` and included in backups
- `/check` and `/gstats` show counts for every built-in and custom rarity

### Player and collection UI

- `/show [name]` sends every matching character separately with its configured rarity emoji
- Character add commands reject media already assigned to another character
- Built-in and custom character add/delete commands continue through the correct handler
- `/xp` level and XP-bar view
- `/fruits` with styled Devil Fruit and category text
- Confirm/Cancel flow before selling a Devil Fruit
- `/mychars` IDs, pagination, two-column buttons, and Check All
- Inline cached-photo/video results are media-only, producing Telegram’s grid-style inline layout
- Inline cached-video results for video characters
- `/c [id]` is the short character-ID lookup command
- `/charslist` shows every configured rarity and emoji
- Challenge buttons removed from inline character results

### Leaderboards and administration

- Interactive `/top`, `/xtop`, `/crewtop`, and `/topchars`
- Leaderboard switching for bounty, level, crew, and character collections
- `/topchars` ranks players by unique characters collected, with total copies as a tie-breaker/display
- Owner can rename an existing custom rarity globally with `/renamerarity [old] -> [new]`
- Owner can override a character's challenge win chance with `/setcharwin [character_id] [percent]` (0–100)
- Owner-only `/addbounty` and `/addxp` using a reply or user ID
- Owner-only `/downloadjson` and confirmed `/restorejson`
- Automatic and manual backups include the fishing sticker, group settings, and pattern state
- Buyer starts a trade with `/trade [price]` by replying to the seller; seller accepts, buyer selects a character, and seller confirms
- Admins can use `/broadcast`, `/forwardall`, `/forwardgroups`, and `/forwardusers`

### Character challenges, giveaways, and moderation

- `/show [name]` keeps page navigation on the same card when Telegram supports media editing; if a media-type conversion is required, it sends the replacement before removing the old card
- Challenge wins show the captured character ID and award the exact challenged character record by ID, avoiding duplicate-name rarity mix-ups
- Character rarity edits update matching collection copies and their rarity emoji; duplicate names are kept separate by ID
- Owner-only `/charitygiveaway [rarity name] [players] [duration]`, e.g. `/charitygiveaway Limited 3 10m`; each selected player wins one random character from that rarity. `players` defaults to 1; brief command replies disappear after 5 seconds
- Owner-only `/bgiveaway [time] [total bounty] [winners] [reason]` can be started in the current group, or from DM with a target group ID first: `/bgiveaway -1001234567890 10m 5000000 3 Celebration`
- Owner can gift a catalog card directly, without owning a copy: `/giftcard [user_id] [character_id]` or reply to a player with `/giftcard [character_id]`; `/givecard` is an alias
- The owner can queue `/setnextdrop [rarity]` in a group (for example, `/setnextdrop MYTHICAL`) for that group’s next character spawn only; from DM use `/setnextdrop [group_id] [rarity]`. `/setnextdrop off` clears the queued override in the selected group
- Observation, Armament, and Conqueror's Haki each level to 3; at Level 3, `/upgradehaki` can enchant the equipped Haki to Advanced for 1 Advanced Coin and ฿500,000,000,000
- Advanced Armament's 100% game-loss recovery costs 3 Haki energy per trigger, allowing at most 3 recoveries from a full 10-point bar; recovery does not trigger without enough energy
- Owner can set separate Advanced Haki unlock GIFs by replying to a Telegram GIF with `/setadvancedhakigif observation`, `/setadvancedhakigif armament`, or `/setadvancedhakigif conqueror`; `/advancedhakigifs` checks configuration and `/clearadvancedhakigif [type]` removes one
- Group users sending 25 messages within 60 seconds are muted for 10 minutes when the bot has permission; messages during the mute are ignored and excluded from character-drop counts
- Fruit categories use **Paramecia, Zoan, Standard Zoan, Ancient Zoan, Mythical Zoan, Artificial Zoan (SMILE), and Logia**; the category display shows the **Model: Sun God Nika** suffix only for Nika. Good/Medium/Bad remain internal shop price pools only
- The Nika fruit is named **Hito Hito no Mi, Model: Nika**; older saved **Gomu Gomu no Mi, Model: Nika** records are normalized when displayed or sold
- **Gomu Gomu no Mi** is also available separately as a **Paramecia** in the Medium shop pool (฿250,000,000)
- Unauthorized admin/owner command attempts receive a clear permission reply instead of an empty message

### Character image-generation preference

- When generating character art for this project, use the user's **Quality 1** style: luminous/shining appearance, very soft-looking skin, and dramatic color treatment. Apply this only when image generation is requested.

### Group permissions and registration

- The bot reacts to group commands and gameplay only while it is an administrator in that group.
- If the bot is not an administrator, group messages are ignored silently.
- `/start` is the only group exception and registers the player before the bot is promoted.
- `/start` continues to work normally in private chat.

### Preserved base modules

The merged project also preserves the base ZIP modules and assets:

- Games, PvP, world boss, giveaways, inventory, crews, Haki, and update notifier
- Channel storage synchronization
- Fonts, wanted poster, requirements, and existing JSON player/character data

## Setup

1. Clone or upload the project.
2. Install dependencies with `pip install -r requirements.txt`.
3. Create a `.env` file with your Telegram credentials and existing bot settings.
4. Set the release variables in Railway:

   ```env
   BOT_VERSION=1.2.0
   BOT_CHANGELOG=🚀 MAJOR UPDATE — VERSION 1.2.0
   ```

5. Start the bot with `python bot.py`.

Do not commit `.env`, Telegram session files, `__pycache__`, or runtime backup/import folders.
