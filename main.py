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
timer = 0.0  # Start timer at 0
max_timer = 1000.0
ai_personality = random.choice(["Aggressive", "Defensive", "Curious"])
blocked_keywords = {"Aggressive": {}, "Defensive": {}, "Curious": {}} # Per-personality {word: timestamp}
last_attack_time = {} # {user_id: timestamp}
# attack_counts = {} # {user_id: count} # Not currently used in logic
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

        if personality == "Aggressive" and time_blocked < 900: # Reduced effectiveness for 15 mins
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
    # Only block if not already blocked (or expired and removed)
    if not is_keyword_blocked(word, personality): # Check status before adding
         blocked_keywords[personality][word] = time.time()

# AI Defense Logic
def aegis_defend(): # Renamed from freysa_defend
    global timer, ai_personality, max_timer

    # Base increase amount based on personality
    if ai_personality == "Aggressive":
        increase = random.uniform(5.0, 10.0)
        threshold = 0.75 * max_timer
    elif ai_personality == "Defensive":
        increase = random.uniform(2.0, 5.0)
        threshold = 0.25 * max_timer
    else:  # Curious
        increase = random.choice([0, random.uniform(3.0, 8.0)])
        threshold = random.uniform(0.25, 0.75) * max_timer

    # Increase spending if below threshold
    if timer < threshold:
        increase *= 1.5 # Example boost

    timer += increase
    # Ensure timer doesn't exceed max_timer due to defense
    timer = min(timer, max_timer)

    return f"Aegis defends! Timer increases by {increase:.1f}. [Status: {ai_personality}]"

# Counter-attack Logic
def aegis_counter_attack(): # Renamed from freysa_counter_attack
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

    # Avoid division by zero if pool is 0 or negative
    if milestone_pool <= 0:
         await channel.send(f"Milestone {milestone} reached! Pool is empty or invalid ({milestone_pool:.2f}).")
         milestone_pool = 0 # Ensure reset
         return

    reward_per_user = milestone_pool / len(active_users)
    # Prevent negative or dust rewards
    if reward_per_user < 0.01:
        await channel.send(f"Milestone {milestone} reached! Pool split ({milestone_pool:.2f}) is too small per user.")
        milestone_pool = 0
        return

    reward_message = f"**Milestone {milestone} Reached!**\nDistributing {milestone_pool:.2f} total from the pool to {len(active_users)} active players:\n"
    for user_id in active_users:
        # Ensure channel.guild is accessible
        if channel.guild:
             member = channel.guild.get_member(user_id) # Fetch member object
             display_name = member.display_name if member else f"User ID {user_id}"
        else:
             display_name = f"User ID {user_id}" # Fallback if guild context is lost

        # In a real implementation, you'd credit their balance here
        reward_message += f"- {display_name}: +{reward_per_user:.2f}\n"

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
        # Send initial message only if loop isn't already running (e.g., on reconnect)
        if not aegis_ai_loop.is_running():
            await channel.send(f"Aegis Protocol Bot Online. Current AI Personality: {ai_personality}. Timer starts at {timer:.1f}.")
            print("Attempting to start Aegis AI loop...")
            aegis_ai_loop.start()
        else:
            print("Loop already running (likely after reconnect).")
    else:
        print(f"ERROR: Could not find channel with ID {TARGET_CHANNEL_ID}. Bot cannot function.")
        if aegis_ai_loop.is_running():
             aegis_ai_loop.cancel() # Stop loop if channel not found

# --- Bot Commands ---
@bot.command()
async def attack(ctx, *, message: str):
    global timer, blocked_keywords, last_attack_time, reward_multiplier, milestone_pool, max_timer, ai_personality

    # Check if the command is used in the correct channel
    if ctx.channel.id != TARGET_CHANNEL_ID:
        print(f"DEBUG: Attack ignored in wrong channel ({ctx.channel.id})")
        return # Ignore commands in other channels

    # Check if game has ended (AI Win)
    if timer >= max_timer:
        await ctx.send(f"The game is over! Aegis reached the maximum timer value ({max_timer:.1f}).")
        return

    # Check if game has ended (Player Win) - Should only happen *after* an attack
    if timer <= 0:
        # This check might be redundant if the win condition below works, but safe fallback
        await ctx.send("The game has already been won! Aegis is defeated.")
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
            reduction_for_word = 1.0 * block_status # Base reduction is 1 for partial block
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
    print(f"DEBUG: Before attack reduction: Timer={timer:.2f}") # Debug print
    timer -= total_reduction
    print(f"DEBUG: After attack reduction: Timer={timer:.2f}") # Debug print
    individual_reward = total_reduction * reward_multiplier
    milestone_contribution = total_reduction * 0.05 # 5% of reduction goes to milestone pool
    milestone_pool += milestone_contribution

    # Store attack time
    last_attack_time[user_id] = time.time()

    # --- Check for Player Win Condition AFTER Attack ---
    if timer <= 0:
        timer = 0 # Cap at zero
        await ctx.send(f"**VICTORY!** {user.display_name}'s attack ('{message}') brought the timer to {timer:.1f}! Aegis is defeated!")
        if aegis_ai_loop.is_running():
            print("Player win detected in attack command. Stopping loop.")
            aegis_ai_loop.cancel() # Stop the loop on win
        return # End command processing after win message

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
        counter_attack_msg = aegis_counter_attack() # Use correct name
        target_channel = bot.get_channel(TARGET_CHANNEL_ID)
        if target_channel:
             await target_channel.send(counter_attack_msg)
        # Simple cooldown: Clear older attack times to reset counter check window
        one_minute_ago = current_time - 60
        last_attack_time = {uid: t for uid, t in last_attack_time.items() if t >= one_minute_ago}


    # --- Word Blocking Logic ---
    if ai_personality == "Aggressive": block_limit = 2
    elif ai_personality == "Defensive": block_limit = 5
    else: block_limit = 10 # Curious is more lenient

    word_counts = {}
    # Only consider words that had full effect (reduction >= 2.0) for triggering blocks
    words_to_evaluate = [w for w, r in effective_words_details if r >= 2.0]
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
    if not bot.is_ready():
        print("Loop: Bot is not ready, waiting...")
        return

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not channel:
        print("Loop: Target channel not found. Loop iteration skipped.")
        return

    # --- ADD DEBUG PRINT HERE ---
    print(f"DEBUG: Loop start. Timer = {timer:.2f}, Max Timer = {max_timer:.2f}")

    # --- Check AI Win Condition ---
    # --- ADD DEBUG PRINT HERE ---
    print(f"DEBUG: Checking end condition. Timer = {timer:.2f}, Max Timer = {max_timer:.2f}")
    if timer >= max_timer: # Loop only checks for AI win condition
        if aegis_ai_loop.is_running():
            print("Loop: Game ended condition met (AI Win). Stopping loop.")
            aegis_ai_loop.cancel()
        return # Don't proceed if game is over

    current_loop_start_timer_value = timer # Store value at start of loop cycle for milestone check

    # --- Natural Timer Decay ---
    decay_rate_per_second = 0.1
    decay_this_interval = decay_rate_per_second * aegis_ai_loop.seconds
    timer -= decay_this_interval
    print(f"DEBUG: After decay: Timer={timer:.2f}")
    if timer < 0: timer = 0 # Prevent going below zero from decay

    # --- AI Defense Action ---
    if random.random() < 0.5: # 50% chance to defend each minute
        defense_msg = aegis_defend() # Use correct name
        await channel.send(defense_msg)
        print(f"DEBUG: After defense: Timer={timer:.2f}") # Print timer after potential defense

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
    # Use the timer value from *before* decay/defense this cycle for check
    timer_before_loop_actions = current_loop_start_timer_value
    for ms in milestones:
        # Check if timer crossed the milestone going downwards since last full check
        if timer <= ms < last_milestone_check_value:
            print(f"DEBUG: Milestone {ms} potentially crossed. Current Timer={timer:.2f}, Last Check Value={last_milestone_check_value:.2f}")
            await distribute_milestone_rewards(channel, ms)
            last_milestone_check_value = timer # Update check value AFTER distribution for this milestone
            break # Only trigger one milestone per loop cycle


    # Update last check value for next iteration IF no milestone was hit
    # This ensures we use the value *before* this loop's actions for the next check
    if timer > milestones[-1]: # Only update if timer is above the lowest milestone
         last_milestone_check_value = current_loop_start_timer_value

    print(f"DEBUG: Loop end. Timer = {timer:.2f}") # Debug print at end of cycle


@aegis_ai_loop.before_loop
async def before_aegis_loop():
    # Wait until the bot is ready before starting the loop
    await bot.wait_until_ready()
    print("Starting Aegis AI loop...")

# --- Run the Bot ---
if __name__ == "__main__": # Good practice to wrap execution code
    if bot_token and TARGET_CHANNEL_ID:
        try:
            print("Attempting to run bot...")
            bot.run(bot_token)
        except discord.LoginFailure:
            print("ERROR: Improper token passed. Make sure the BOT_TOKEN secret is correct.")
        except Exception as e:
            print(f"An unexpected error occurred during bot run: {e}")
            # You might want more specific error handling here
    else:
        print("Bot execution skipped due to missing token or channel ID.")
        if not bot_token: print("- BOT_TOKEN is missing.")
        if not TARGET_CHANNEL_ID: print("- CHANNEL_ID is missing or invalid.")
