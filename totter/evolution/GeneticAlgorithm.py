""" Abstract base class for a simple GA

This GA will always seek to maximize fitness
"""

import copy
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import pickle
import random

from abc import abstractmethod
from matplotlib.ticker import MaxNLocator

from totter.api.qwop import QwopEvaluator
from totter.evolution.QwopStrategy import QwopStrategy
import totter.utils.storage as storage
from totter.utils.time import WallTimer


class GeneticAlgorithm(object):
    def __init__(self,
                 evaluations=2000,
                 eval_time_limit=600,
                 pop_size=20,
                 cx_prob=0.9,
                 mt_prob=0.05,
                 steady_state=True,
                 seed=1234):

        self.random_seed = seed

        self.eval_time_limit = eval_time_limit
        self.qwop_evaluator = QwopEvaluator(time_limit=self.eval_time_limit)

        self.pop_size = pop_size
        self.cx_prob = cx_prob
        self.mt_prob = mt_prob
        self.steady_state = steady_state

        # variables that track progress
        self.total_evaluations = 0
        self.generations = 1
        self.max_evaluations = evaluations
        self.best_indv = None
        self.history = []  # stores (generation, best_fitness, average_fitness) tuples

        # seed RNG
        random.seed(self.random_seed)

        # create a random population
        self.population = [Individual(self.generate_random_genome()) for i in range(0, self.pop_size)]
        self.best_indv = self.population[0]

    def plot(self, save=False):
        """ Plot the algorithm's history of best fitness and average fitness

        Args:
            save (bool): if set, the plot will be saved to the RESULTS directory instead of shown

        Returns: None

        """
        history = np.array(self.history)

        generations = history[:, 0]
        best = history[:, 1]
        average = history[:, 2]

        fig, ax1 = plt.subplots()
        # label the axes
        ax1.set_xlabel("Generation")
        ax1.set_ylabel("Fitness")
        # make `generations` axis show integer labels
        ax = fig.gca()
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        line1 = ax1.plot(generations, best, "b-", label="Best Fitness")
        line2 = ax1.plot(generations, average, "r-", label="Average fitness")

        # construct legend
        lns = line1 + line2
        labs = [l.get_label() for l in lns]
        ax1.legend(lns, labs, loc="center right")

        if save:
            save_path = storage.get(os.path.join(self.__class__.__name__, 'figures'))
            plt.savefig(os.path.join(save_path, 'fitness_vs_time.png'))
        else:
            plt.show()

    @classmethod
    def get_results_path(cls):
        save_path = storage.get(os.path.join(cls.__name__, 'results'))
        file_path = os.path.join(save_path, 'results.json')
        return file_path

    def save_results(self):
        """ Save the best individual, his fitness, the average fitness, and related graphs

        Returns:
            str: path to the directory where results are saved

        """
        data = {
            'name': self.__class__.__name__,
            'config': {
                'evaluations': self.max_evaluations,
                'eval_time_limit': self.eval_time_limit,
                'pop_size': self.pop_size,
                'cx_prob': self.cx_prob,
                'mt_prob': self.mt_prob,
                'steady_state': self.steady_state,
                'seed': self.random_seed
            },
            'best_individual': self.best_indv.genome,
            'best_fitness': self.best_indv.fitness,
            'average_fitness': sum(map(lambda indv: indv.fitness, self.population)) / len(self.population)
        }

        # save the best individual and his fitness
        with open(self.get_results_path(), 'w') as data_file:
            json.dump(data, data_file)

        # save the related plot
        self.plot(save=True)

        return self.get_results_path()

    def save_current_state(self):
        """ Serialize the current state of the GA to disk

        This method serializes all the info needed to restart the GA from the current state.

        Returns: None

        """

        data = {
            'name': self.__class__.__name__,
            'population': self.population,
            'generations': self.generations,
            'total_evaluations': self.total_evaluations,
            'history': self.history,
            'config': {
                'evaluations': self.max_evaluations,
                'eval_time_limit': self.eval_time_limit,
                'pop_size': self.pop_size,
                'cx_prob': self.cx_prob,
                'mt_prob': self.mt_prob,
                'steady_state': self.steady_state,
                'seed': self.random_seed
            },
            'best_individual': self.best_indv
        }
        save_path = storage.get(os.path.join(self.__class__.__name__, 'progress'))
        with open(os.path.join(save_path, 'progress.totter'), 'wb') as data_file:
            pickle.dump(data, data_file)

    def load(self):
        """ Reset the GA to the state matching its most recent progress file

        Returns: bool: True if loading was successful, False otherwise

        """
        save_path = storage.get(os.path.join(self.__class__.__name__, 'progress'))
        save_filepath = os.path.join(save_path, 'progress.totter')
        if os.path.exists(save_filepath):
            with open(save_filepath, 'rb') as data_file:
                data = pickle.load(data_file)
                self.population = data['population']
                self.generations = data['generations']
                self.total_evaluations = data['total_evaluations']
                self.history = data['history']
                config = data['config']
                self.max_evaluations = data['total_evaluations'] + self.max_evaluations
                self.qwop_evaluator.time_limit = config['eval_time_limit']
                self.pop_size = config['pop_size']
                self.cx_prob = config['cx_prob']
                self.mt_prob = config['mt_prob']
                self.steady_state = config['steady_state']
                self.random_seed = config['seed']
                random.seed(self.random_seed)
                self.best_indv = data['best_individual']

            return True

        return False

    def seed(self, pool_size, time_limit=60):
        """ Seeds the initial population with good randomly-created runners

        This selects the best `self.pop_size` individuals from a pool of randomly generated individuals.
        If the seeding procedure has already been run, then the individuals will instead be loaded from disk

        Args:
            pool_size (int): the size of the randomly generated pool from which the initial population will be drawn
            time_limit (int): time limit (in seconds) for each evaluation in the pool

        Returns: None

        """
        population_filepath = storage.get(os.path.join(self.__class__.__name__, 'population_seeds'))
        population_file = os.path.join(population_filepath, f'seed_{self.pop_size}.tsd')

        # if the population has not previously been seeded, then generate the seeded pop
        if not os.path.exists(population_file):
            # temporarily set time limit
            self.qwop_evaluator.simulator.time_limit = time_limit
            # generate pool of random individuals
            pool = [Individual(self.generate_random_genome()) for i in range(0, pool_size)]
            for indv in pool:
                # custom evaluation
                phenotype = self.genome_to_phenotype(indv.genome)
                strategy = QwopStrategy(execution_function=phenotype)
                distance, run_time = self.qwop_evaluator.evaluate(strategy)[0]
                indv.fitness = distance

            # sort by descending fitness
            sorted_pool = sorted(pool, key=lambda individual: -individual.fitness)
            # grab the fittest individuals
            population = sorted_pool[:pool_size]
            # save the seeded population
            with open(population_file, 'wb') as data_file:
                pickle.dump(population, data_file)

            # reset GA state
            self.qwop_evaluator.simulator.time_limit = self.eval_time_limit  # reset the time limit for the GA

        # load population from saved file
        with open(population_file, 'rb') as data_file:
            seeded_pop = pickle.load(data_file)
            self.population = seeded_pop
            self.best_indv = self.population[0]
            # reset fitness values - the fitness used by the GA may be different than the fitness used by the seeder
            for indv in self.population:
                indv.fitness = None

    def run(self):
        """ Runs the GA until the maximum number of iterations is achieved

        Returns: time taken during the run (in seconds)

        """
        # ensure population has been evaluated and best_indv is up-to-date
        # this is necesary after a GA is constructed or after loading a GA from disk
        for indv in self.population:
            if indv.fitness is None:
                self._evaluate(indv)
            if self.best_indv.fitness is None or indv.fitness > self.best_indv.fitness:
                self.best_indv = indv

        # time the run
        timer = WallTimer()
        while self.total_evaluations < self.max_evaluations:
            # select parents
            if self.steady_state:
                parents = self.select_parents(self.population, 2)
            else:
                parents = self.select_parents(self.population, self.pop_size)

            # make children using crossover
            offspring = list()
            for parent1, parent2 in zip(parents[::2], parents[1::2]):
                if random.random() < self.cx_prob:
                    child1_genome, child2_genome = self.crossover(parent1.genome, parent2.genome)
                    offspring.append(child1_genome)
                    offspring.append(child2_genome)

            # mutate then repair
            for idx in range(0, len(offspring)):
                child_genome = offspring[idx]
                if random.random() < self.mt_prob:
                    child_genome = self.mutate(child_genome)

                child_genome = self.repair(child_genome)

                # even if the child wasn't mutated, his fitness needs to be re-evaluated
                child = Individual(genome=child_genome)
                self._evaluate(child)
                offspring[idx] = child

            # update population
            for child in offspring:
                # update best individual the GA has found so far
                if self.best_indv is None or child.fitness > self.best_indv.fitness:
                    self.best_indv = child

                # do replacement
                replacement_index = self.replace(self.population, child)
                if replacement_index is not None:
                    self.population[replacement_index] = child

            # record history
            if self.best_indv is not None:
                best_fitness = self.best_indv.fitness
                average_fitness = sum(map(lambda indv: indv.fitness, self.population)) / len(self.population)
                self.history.append([self.generations, best_fitness, average_fitness])

            self.generations += 1

        return timer.since()

    def _evaluate(self, individual):
        """ Evaluates an indvidual using the QwopEvaluator, updates the individual's fitness, and increments the counter

        Args:
            individual (Individual): the indvidual to evaluate

        Returns:

        """
        phenotype = self.genome_to_phenotype(individual.genome)
        strategy = QwopStrategy(execution_function=phenotype)
        distance, run_time = self.qwop_evaluator.evaluate(strategy)[0]
        individual.fitness = self.compute_fitness(distance, run_time)
        self.total_evaluations += 1

    @abstractmethod
    def generate_random_genome(self):
        """ Generates a random genome

        Returns:
            object: randomly generated genome

        """
        pass

    @abstractmethod
    def genome_to_phenotype(self, genome):
        """ Convert a genome to a function that plays QWOP

        For example, if the genome is [W, Q, P], then the phenotype might be a function that presses 'W',
        then presses 'Q', then presses 'P'.

        Returns:
            function: function that implements the strategy suggested by the genome

        """
        pass

    @abstractmethod
    def compute_fitness(self, distance_run, run_time):
        """ Computes an individual's fitness from the distance run and the time it took

        Args:
            distance_run (float): distance run in the QWOP simulator
            run_time (float): time in seconds that it took to run to `distance`

        Returns:
            float: computed fitness

        """
        pass

    @abstractmethod
    def select_parents(self, population, n):
        """ Selects `n` members for parenthood from `population`

        Args:
            population (list): the current population
            n (int): the number of parents to select

        Returns:
            list<Individual>: the individuals selected for parenthood

        """
        pass

    @abstractmethod
    def crossover(self, parent1, parent2):
        """ Crossover parent1 with parent2 and generate two offspring

        Args:
            parent1: the genome of the first parent
            parent2: the genome of the second parent

        Returns:
            (object, object): (genome of child 1, genome of child 2)

        """
        pass

    @abstractmethod
    def mutate(self, genome):
        """ Perform mutation on the provided genome

        Args:
            genome (object): genome to mutate

        Returns:
            object: mutated genome

        """
        pass

    @abstractmethod
    def repair(self, genome):
        """ Repair a genome after crossover or mutation

        Args:
            genome (object): genome to repair

        Returns:
            object: genome with repaired contents

        """
        pass

    @abstractmethod
    def replace(self, population, candidate):
        """ Select a member of the population which will be replaced by `candidate`

        This method should return the index of the population member to replace.
        It may also return None, which indicates that `candidate` should be discarded instead of replacing a member
        of the population

        Args:
            population (list<Individual>:
                list of Individuals in the population. Each individual has a genome and a fitness.

            candidate (Individual): Individual which will replace the selected member

        Returns:
            int or None:
                index of population member to be replaced by `candidate`,
                or None if the replacement should not occur

        """
        pass


class Individual:
    def __init__(self, genome):
        self.genome = genome
        self.fitness = None

    def clone(self):
        cloned_self = Individual(copy.deepcopy(self.genome))
        cloned_self.fitness = self.fitness
        return cloned_self

    def __str__(self):
        return f'Individual: {self.genome}\nFitness: {self.fitness}'

    def __len__(self):
        return len(self.genome)
