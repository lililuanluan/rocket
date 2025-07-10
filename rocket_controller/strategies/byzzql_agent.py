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
        
        # todo: initial values are 0 for state-action pair
        #self.q_table
        
    def choose_action(self, state_hash: str) -> str:
        # todo: first check if we have budget for testing

        if random.random() < self.epsilon:
            # exploration
            action = random.choice(self.action_space)
            logger.debug(f"RL Agent: Exploring with random action '{action}'")
        else:
            # exploitation
            # todo: choose best decision based on Q-table
            action = "DELAY"
            logger.debug(f"RL Agent: Exploiting with action '{action}'")
            
        return action
    
    #def update_q_value(self, state: str, action: str, reward: float, next_state: str):
        # todo: update q-table