import random
from abc import ABC, abstractmethod

from deap import tools


class CrossoverOperator(ABC):

    @abstractmethod
    def crossover(self, population: list[list[int]]):
        return population

class SBX(CrossoverOperator):
    def crossover(self, population: list[list[int]]):
        new_population = []

        # SBX crossover parameters
        eta = 20.0  # Distribution index for crossover

        for i in range(0, len(population), 2):
            # Get two parents
            parent1 = population[i]
            parent2 = population[i + 1] if i + 1 < len(population) else population[0]

            # Perform Simulated Binary Crossover
            child1, child2 = tools.cxSimulatedBinary(parent1[:], parent2[:], eta)

            new_population.extend([child1, child2])
        return new_population


class MutationOperator(ABC):

    @abstractmethod
    def mutate(self, population: list[list[int]]):
        return population

class GaussianMutation(MutationOperator):

    def __init__(self, encoding_min: int, encoding_max: int):
        self.encoding_min = encoding_min
        self.encoding_max = encoding_max

    def mutate(self, population: list[list[int]]):

        # Gaussian mutation parameters
        mu = 0.0  # Mean for gaussian mutation
        sigma = 0.2  # Standard deviation for gaussian mutation
        mutation_prob = 0.1  # Probability of mutation for each gene

        # Perform Gaussian Mutation on both children
        for child in population:
            for j in range(len(child)):
                if random.random() < mutation_prob:
                    child[j] += random.gauss(mu, sigma)
                    # Ensure values stay within bounds
                    child[j] = max(self.encoding_min, min(self.encoding_max, child[j]))

        return population