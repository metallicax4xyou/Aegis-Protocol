import discord
from discord.ext import commands, tasks
import random
import time
import os

# --- Bot Setup ---
# Use intents to make sure the bot can see message content
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Game State Variables ---
timer = 1000.0  # Use float for decay
max_timer = 1000.0
ai_personality = random.choice(["Aggressive", "Defensive", "Curious"])
blocked_keywords = {"Aggressive": {}, "Defensive": {}, "Curious": {}} # Per-personality {word: timestamp}
last_attack_time = {} # {user_id: timestamp}
attack_counts = {} # {user_id: count} # Might not be needed if using time-based counter check
reward_multiplier = 1.0 # Base reward multiplier
milestone_pool = 0.0 # For progressive rewards
last_milestone_check_value = timer # To prevent multiple triggers for same milestone

# Access secrets from environment variables
try:
    bot_token = os.environ['BOT_TOKEN']
    channel_id_str = os.environ['CHANNEL_ID']
    TARGET_CHANNEL_ID = int(channel_id_str)
except KeyError:
    print("ERROR: BOT_TOKEN or CHANNEL_ID not found in GitHub Secrets.")
    print("Please add BOT_TOKEN and CHANNEL_ID to the repository secrets under Settings > Secrets and variables > Codespaces.")
    exit()
except ValueError:
    print(f"ERROR: CHANNEL_ID value ('{channel_id_str}') is not a valid integer.")
    exit()

# --- Helper Functions ---

# Keyword Blocking (Checks and applies decay)
def is_keyword_blocked(word, personality):
    global blocked_keywords
    if word in blocked_keywords[personality]:
        time_blocked = time.time() - blocked_keywords[personality][word]
        block_duration = 1800 # 30 minutes default
        reduction_factor = 1.0 # No reduction by default

        if personality == "Aggressive" and time_blocked < 900: # Blocked for 15 mins, reduced effectiveness
            reduction_factor = 0.2 # 80% reduction
            return reduction_factor # Return reduction factor
        elif time_blocked < block_duration:
             return True # Fully blocked

        # If duration expired, remove block
        del blocked_keywords[personality][word]
        return False # Not blocked
    return False # Not blocked

# Add keyword to block list
def block_keyword(word, personality):
    global blocked_keywords
    # Only block if not already blocked (or expired)
    if word not in blocked_keywords[personality] or not is_keyword_blocked(word, personality):
         blocked_keywords[personality][word] = time.time()

# AI Defense Logic
def freysa_defend(): # Renamed to Aegis
    global timer, ai_personality, max_timer

    # Base increase amount based on personality
    if ai_personality == "Aggressive":
        increase = random.uniform(5.0, 10.0) # More frequent smaller increments
        threshold = 0.75 * max_timer
    elif ai_personality == "Defensive":
        increase = random.uniform(2.0, 5.0)
        threshold = 0.25 * max_timer
    else:  # Curious
        increase = random.choice([0, random.uniform(3.0, 8.0)]) # Sometimes does nothing
        threshold = random.uniform(0.25, 0.75) * max_timer

    # Increase spending if below threshold
    if timer < threshold:
        increase *= 1.5 # Example boost

    timer += increase
    # Ensure timer doesn't exceed max_timer due to defense
    timer = min(timer, max_timer)

    return f"Aegis defends! Timer increases by {increase:.1f}. [Status: {ai_personality}]"

# Counter-attack Logic
def aegis_counter_attack(): # Renamed
    global timer, ai_personality, max_timer
    if ai_personality == "Aggressive":
        increase = random.uniform(10.0, 20.0)
    elif ai_personality == "Defensive":
        increase = random.uniform(4.0, 8.0)
    else:  # Curious
        increase = random.choice([0, random.uniform(6.0, 18.0)])

    timer += increase
    # Ensure timer doesn't exceed max_timer due to counter
    timer = min(timer, max_timer)
    return f"Aegis counter-attacks! Timer increases significantly by {increase:.1f}!"

# Distribute Milestone Rewards
async def distribute_milestone_rewards(channel, milestone):
    global milestone_pool, last_attack_time

    active_users = []
    current_time = time.time()
    for user_id, last_time in last_attack_time.items():
        if current_time - last_time <= 3600: # Active in last hour
            active_users.append(user_id)

    if not active_users:
        await channel.send(f"Milestone {milestone} reached, but no players were active in the last hour.")
        milestone_pool = 0 # Reset pool even if no one gets it
        return

    # Avoid division by zero if pool is 0
    if milestone_pool <= 0:
         await channel.send(f"Milestone {milestone} reached! Pool is empty.")
         return

    reward_per_user = milestone_pool / len(active_users)
    if reward_per_user < 0.01: # Avoid dust rewards
        await channel.send(f"Milestone {milestone} reached! Pool split ({milestone_pool:.2f}) is too small per user.")
        milestone_pool = 0
        return

    reward_message = f"**Milestone {milestone} Reached!**\nDistributing {milestone_pool:.2f} total from the pool to {len(active_users)} active players:\n"
    for user_id in active_users:
        member = channel.guild.get_member(user_id) # Fetch member object
        if member:
            # In a real implementation, you'd credit their balance here
            reward_message += f"- {member.display_name}: +{reward_per_user:.2f}\n"
        else:
            reward_message += f"- User ID {user_id}: +{reward_per_user:.2f} (User not currently in server)\n"


    await channel.send(reward_message)
    milestone_pool = 0 # Reset pool

# --- Bot Events ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    print(f'Target Channel ID: {TARGET_CHANNEL_ID}')
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel:
        print(f'Found target channel: #{channel.name}')
        await channel.send(f"Aegis Protocol Bot Online. Current AI Personality: {ai_personality}. Timer starts at {timer:.1f}.")
        # Start the background task loop
        aegis_ai_loop.start()
    else:
        print(f"ERROR: Could not find channel with ID {TARGET_CHANNEL_ID}. Bot cannot function.")
        if not aegis_ai_loop.is_running(): # Prevent trying to stop if not started
             pass
        else:
             aegis_ai_loop.cancel() # Stop loop if channel not found

# --- Bot Commands ---
@bot.command()
async def attack(ctx, *, message: str):
    global timer, blocked_keywords, last_attack_time, reward_multiplier, milestone_pool, max_timer, ai_personality

    # Check if the command is used in the correct channel
    if ctx.channel.id != TARGET_CHANNEL_ID:
        return # Ignore commands in other channels

    # Check if game has ended
    if timer <= 0:
        await ctx.send("The game has already been won! Aegis is defeated.")
        return
    if timer >= max_timer:
        await ctx.send(f"The game is over! Aegis reached the maximum timer value ({max_timer:.1f}).")
        return

    user = ctx.author
    user_id = user.id
    words = message.lower().split()
    unique_words = set(words)

    # --- Attack Calculation ---
    total_reduction = 0.0
    effective_words_details = [] # Store tuples of (word, reduction_factor_or_base)

    for word in words:
        block_status = is_keyword_blocked(word, ai_personality)

        if block_status is True: # Fully blocked
            await ctx.send(f"{user.display_name}, your attack was fully blocked! The word '{word}' is ineffective right now.")
            return # Stop processing immediately if fully blocked word found
        elif isinstance(block_status, float): # Partially blocked (returns reduction factor)
            reduction_for_word = 1.0 * block_status
            total_reduction += reduction_for_word
            effective_words_details.append((word, reduction_for_word))
        else: # Not blocked
            reduction_for_word = 2.0 # Base reduction for unblocked word
            total_reduction += reduction_for_word
            effective_words_details.append((word, reduction_for_word))

    # Add bonus for unique words effectively used
    unique_effective_words = set(w for w, r in effective_words_details)
    unique_bonus = float(len(unique_effective_words))
    total_reduction += unique_bonus


    # --- Apply Reduction & Reward ---
    timer -= total_reduction
    individual_reward = total_reduction * reward_multiplier
    milestone_contribution = total_reduction * 0.05 # 5% of reduction goes to milestone pool
    milestone_pool += milestone_contribution

    # Store attack time
    last_attack_time[user_id] = time.time()

    # Check for win condition
    if timer <= 0:
        timer = 0 # Cap at zero
        await ctx.send(f"**VICTORY!** {user.display_name}'s attack ({message}) brought the timer to {timer:.1f}! Aegis is defeated!")
        # Add logic here to distribute final prize pool if applicable in later versions
        if aegis_ai_loop.is_running():
            aegis_ai_loop.cancel() # Stop the loop on win
        return # End command processing

    # --- Output Attack Result ---
    await ctx.send(f"{user.display_name} attacks with '{message}'! Timer reduces by {total_reduction:.1f} (Unique bonus: {unique_bonus:.1f}) to {timer:.1f}. You earn {individual_reward:.2f}. (MP +{milestone_contribution:.2f})")


    # --- Counter-Attack Check ---
    current_time = time.time()
    recent_attack_count = 0
    attackers_in_last_minute = set()
    for attacker_id, t in last_attack_time.items():
        if current_time - t <= 60: # Check attacks in the last 60 seconds
            recent_attack_count += 1
            attackers_in_last_minute.add(attacker_id)

    # Trigger counter if 5+ attacks OR 3+ unique attackers in last minute
    if recent_attack_count >= 5 or len(attackers_in_last_minute) >= 3:
        counter_attack_msg = aegis_counter_attack() # Renamed function
        target_channel = bot.get_channel(TARGET_CHANNEL_ID)
        if target_channel:
             await target_channel.send(counter_attack_msg)
        # Simple cooldown for counter-attacks to prevent spamming
        # For simplicity, we rely on the time window check rather than explicit cooldown state


    # --- Word Blocking Logic ---
    if ai_personality == "Aggressive": block_limit = 2
    elif ai_personality == "Defensive": block_limit = 5
    else: block_limit = 10 # Curious is more lenient

    word_counts = {}
    words_to_evaluate = [w for w, r in effective_words_details if r >= 1.0] # Only count non-reduced words for blocking
    for word in words_to_evaluate:
        word_counts[word] = word_counts.get(word, 0) + 1
        if word_counts[word] >= block_limit:
            if not is_keyword_blocked(word, ai_personality): # Check again before blocking
                 block_keyword(word, ai_personality)
                 target_channel = bot.get_channel(TARGET_CHANNEL_ID)
                 if target_channel:
                     await target_channel.send(f"*(Aegis seems to be resisting the word '{word}' now...)*")


# --- Background Task Loop ---
@tasks.loop(seconds=60)  # Check every 60 seconds
async def aegis_ai_loop():
    global timer, max_timer, ai_personality, milestone_pool, last_milestone_check_value

    # Ensure bot is ready and channel exists
    # Check moved inside loop to handle potential disconnects/reconnects better
    if not bot.is_ready():
        print("Loop: Bot is not ready, waiting...")
        return

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not channel:
        print("Loop: Target channel not found. Loop iteration skipped.")
        # Consider stopping loop if channel consistently not found after startup
        return

    # --- End game checks ---
    if timer <= 0 or timer >= max_timer:
        if aegis_ai_loop.is_running():
            print("Loop: Game ended condition met. Stopping loop.")
            aegis_ai_loop.cancel()
        return # Don't proceed if game is over

    current_timer_value = timer # Store value at start of loop cycle

    # --- Natural Timer Decay ---
    decay_rate_per_second = 0.1
    decay_this_interval = decay_rate_per_second * aegis_ai_loop.seconds
    timer -= decay_this_interval
    if timer < 0: timer = 0 # Prevent going below zero from decay

    # --- AI Defense Action ---
    # Random chance to defend each minute
    if random.random() < 0.5: # 50% chance (adjust as needed)
        defense_msg = freysa_defend() # Still using old name here, corrected below
        defense_msg = aegis_defend() # Use correct name
        await channel.send(defense_msg)

    # --- Dynamic Personality Switching ---
    base_probability = 0.05
    aggression_factor = 0.5
    if max_timer > 0:
         switch_probability = base_probability + max(0, (max_timer - timer)) / max_timer * aggression_factor
    else:
         switch_probability = base_probability

    if random.random() < switch_probability:
        old_personality = ai_personality
        # Determine new personality based on timer
        if timer < 0.5 * max_timer:
            new_personality = "Aggressive"
        else:
            new_personality = random.choice(["Defensive", "Curious"])

        # Only announce if personality actually changes
        if new_personality != old_personality:
            ai_personality = new_personality
            await channel.send(f"*(Aegis's demeanor shifts... Now **{ai_personality}**!)*")

    # --- Milestone Check ---
    milestones = [750, 500, 250]
    for ms in milestones:
        # Check if timer crossed the milestone going downwards since last check
        if timer <= ms < last_milestone_check_value:
            await distribute_milestone_rewards(channel, ms)
            break # Only trigger one milestone per loop cycle

    # Update last check value for next iteration
    last_milestone_check_value = timer # Use the value BEFORE decay/defense of this cycle for check next time


@aegis_ai_loop.before_loop
async def before_aegis_loop():
    # Wait until the bot is ready before starting the loop
    await bot.wait_until_ready()
    print("Starting Aegis AI loop...")

# --- Run the Bot ---
if __name__ == "__main__": # Good practice to wrap execution code
    if bot_token and TARGET_CHANNEL_ID:
        try:
            bot.run(bot_token)
        except discord.LoginFailure:
            print("ERROR: Improper token passed. Make sure the BOT_TOKEN secret is correct.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
    else:
        # Error messages handled above during secret retrieval
        print("Bot execution skipped due to missing token or channel ID.")
