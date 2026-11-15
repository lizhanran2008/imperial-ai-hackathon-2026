"""Always All-In Bot (bot.py)"""
class Agent:
    def __init__(self):
        self.seat = None

    def on_table_start(self, info):
        self.seat = info.get("seat") if isinstance(info, dict) else None

    def act(self, state):
        legal = state.get("legal_actions", [])

        # Always shove all-in if legal
        if "all_in" in legal:
            return {"action": "all_in"}
        
        # Fallbacks if all_in is somehow unavailable
        if "raise" in legal:
            return {"action": "raise", "amount": state.get("max_raise_to", 2000)}
        if "call" in legal:
            return {"action": "call"}
        if "check" in legal:
            return {"action": "check"}
        if "fold" in legal:
            return {"action": "fold"}
            
        return {"action": "fold"}

    def on_hand_end(self, summary):
        pass