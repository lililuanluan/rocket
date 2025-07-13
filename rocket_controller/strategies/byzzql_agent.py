import random
import hashlib
from collections import defaultdict
from typing import List, Dict, Any
import pickle
import numpy as np
from loguru import logger

class ByzzQLAgent:
    def __init__(self, action_space: List[str], alpha: float = 0.3, gamma: float = 0.7, epsilon: float = 0.1):
        """
        Initialize the ByzzQL reinforcement learning agent
        
        Args:
            action_space: List of possible actions ["DROP", "DELAY", "MUTATE", "DELIVER"]
            alpha: Learning rate
            gamma: Discount factor
            epsilon: exploration rate
        """
        self.action_space = action_space
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        
        # Q-table: initial values are 0.0 for each state-action pair
        self.q_table = defaultdict(lambda: {action: 0.0 for action in self.action_space}) 
        
    def choose_action(self, state_hash: str) -> str:
        if random.random() < self.epsilon:
            # exploration
            action = random.choice(self.action_space)
            logger.debug(f"RL Agent: Exploring with random action '{action}'")
        else:
            # exploitation: choose best action based on Q-table
            q_values = self.q_table[state_hash]
            max_q_value = max(q_values.values())
            best_actions = [action for action, q_val in q_values.items() if q_val == max_q_value]
            action = random.choice(best_actions)  # break ties randomly
            logger.debug(f"RL Agent: Exploiting with action '{action}' (Q={max_q_value:.3f})")
        return action
    
    def update_q_value(self, state: str, action: str, next_state: str):
        """
        Update Q-table using Q-learning formula:
        Q(s,a) = (1-alpha)*Q(s,a) + alpha*(-1+gamma*maxFutureValue))
        """
        current_q = self.q_table[state][action]

        next_q_values = self.q_table[next_state]
        max_next_q = max(next_q_values.values()) if next_q_values else 0.0
        
        new_q = (1-self.alpha) * current_q + self.alpha * (-1 + self.gamma * max_next_q)
        self.q_table[state][action] = new_q
        
        logger.debug(f"Q-Update: State={state[:8]}... Action={action} "
                    f"Q: {current_q:.3f} -> {new_q:.3f}")