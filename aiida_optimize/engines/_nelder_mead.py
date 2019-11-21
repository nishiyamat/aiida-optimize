# -*- coding: utf-8 -*-

# ******NOTICE***************
# optimize.py module by Travis E. Oliphant
#
# You may copy and use this module as you see fit with no
# guarantee implied provided you keep this notice in all copies.
# *****END NOTICE************
#
# The additional license terms given in ADDITIONAL_TERMS.txt apply to this
# file.
# pylint: disable=invalid-name

# © 2017-2019, ETH Zurich, Institut für Theoretische Physik
# Author: Dominik Gresch <greschd@gmx.ch>
"""
Defines a Nelder-Mead optimization engine.
"""

from __future__ import division, print_function, unicode_literals

import numpy as np
import scipy.linalg as la
from aiida.orm import List
from decorator import decorator
from fsc.export import export

from ._base import OptimizationEngineImpl, OptimizationEngineWrapper

RHO = 1
CHI = 2
PSI = 0.5
SIGMA = 0.5


def update_method(next_submit=None):
    """
    Decorator for methods which update the results.
    """
    @decorator
    def inner(func, self, outputs):
        self.next_submit = next_submit
        self.next_update = None
        func(self, outputs)

    return inner


def submit_method(next_update=None):
    """
    Decorator for methods which submit new evaluations.
    """
    @decorator
    def inner(func, self):
        self.next_submit = None
        self.next_update = next_update
        return func(self)

    return inner


class _NelderMeadImpl(OptimizationEngineImpl):
    """
    Implementation class for the Nelder-Mead optimization engine.
    """
    def __init__(  # pylint: disable=too-many-arguments
        self,
        simplex,
        fun_simplex,
        xtol,
        ftol,
        max_iter,
        input_key,
        result_key,
        logger,
        num_iter=0,
        extra_points=None,
        next_submit='submit_initialize',
        next_update=None,
        finished=False,
        result_state=None,
    ):
        super(_NelderMeadImpl, self).__init__(logger=logger, result_state=result_state)

        self.simplex = np.array(simplex)
        assert len(self.simplex) == self.simplex.shape[1] + 1

        if fun_simplex is None:
            self.fun_simplex = None
        else:
            self.fun_simplex = np.array(fun_simplex)

        self.xtol = xtol
        self.ftol = ftol

        self.max_iter = max_iter
        self.num_iter = num_iter

        if extra_points is None:
            self.extra_points = {}
        else:
            self.extra_points = dict(extra_points)

        self.input_key = input_key
        self.result_key = result_key

        self.next_submit = next_submit
        self.next_update = next_update

        self.finished = finished

    def _get_values(self, outputs):
        return [res[self.result_key].value for _, res in sorted(outputs.items())]

    def _get_single_result(self, outputs):
        (idx, ) = outputs.keys()
        x = np.array(self._result_mapping[idx].input[self.input_key].get_attribute('list'))
        f = outputs[idx][self.result_key].value
        return x, f

    @submit_method(next_update='update_initialize')
    def submit_initialize(self):
        self._logger.report('Submitting initialization step.')
        return [self._to_input_list(x) for x in self.simplex]

    def _to_input_list(self, x):
        input_list = List()
        input_list.extend(x)
        return {self.input_key: input_list}

    @update_method(next_submit='new_iter')
    def update_initialize(self, outputs):
        self.fun_simplex = np.array(self._get_values(outputs))

    @submit_method()
    def new_iter(self):  # pylint: disable=missing-docstring
        self.do_sort()
        self.check_finished()
        if self.finished:
            self.next_update = 'finalize'
            return []
        self.num_iter += 1
        xr = (1 + RHO) * self.xbar - RHO * self.simplex[-1]
        self.next_update = 'choose_step'
        return [self._to_input_list(xr)]

    @update_method()
    def finalize(self, outputs):
        pass

    @property
    def xbar(self):
        return np.average(self.simplex[:-1], axis=0)

    def do_sort(self):
        idx = np.argsort(self.fun_simplex)
        self.fun_simplex = np.take(self.fun_simplex, idx, axis=0)
        self.simplex = np.take(self.simplex, idx, axis=0)

    def check_finished(self):
        """
        Updates the 'finished' attribute.
        """
        x_dist_max = np.max(la.norm(self.simplex[1:] - self.simplex[0], axis=-1))
        self._logger.report('Maximum distance value for the simplex: {}'.format(x_dist_max))
        f_diff_max = np.max(np.abs(self.fun_simplex[1:] - self.fun_simplex[0]))
        self._logger.report('Maximum function difference: {}'.format(f_diff_max))
        self.finished = (x_dist_max < self.xtol) and (f_diff_max < self.ftol)

    @update_method()
    def choose_step(self, outputs):
        """
        Method which selects the next step to be performed.
        """
        xr, fxr = self._get_single_result(outputs)
        self.extra_points = {'xr': (xr, fxr)}
        if fxr < self.fun_simplex[0]:
            self.next_submit = 'submit_expansion'
        else:
            if fxr < self.fun_simplex[-2]:
                self._update_last(xr, fxr)
                self.next_submit = 'new_iter'
            else:
                if fxr < self.fun_simplex[-1]:
                    self.next_submit = 'submit_contraction'
                else:
                    self.next_submit = 'submit_inside_contraction'

    def _update_last(self, x, f):
        self.simplex[-1] = x
        self.fun_simplex[-1] = f

    @submit_method(next_update='update_expansion')
    def submit_expansion(self):
        self._logger.report('Submitting expansion step.')
        xe = (1 + RHO * CHI) * self.xbar - RHO * CHI * self.simplex[-1]
        return [self._to_input_list(xe)]

    @update_method(next_submit='new_iter')
    def update_expansion(self, outputs):
        """
        Retrieve the results of an expansion step.
        """
        xe, fxe = self._get_single_result(outputs)
        xr, fxr = self.extra_points['xr']
        if fxe < fxr:
            self._update_last(xe, fxe)
        else:
            self._update_last(xr, fxr)

    @submit_method(next_update='update_contraction')
    def submit_contraction(self):
        self._logger.report('Submitting contraction step.')
        xc = (1 + PSI * RHO) * self.xbar - PSI * RHO * self.simplex[-1]
        return [self._to_input_list(xc)]

    @update_method()
    def update_contraction(self, outputs):
        """
        Retrieve the results of a contraction step.
        """
        xc, fxc = self._get_single_result(outputs)
        _, fxr = self.extra_points['xr']
        if fxc < fxr:
            self._update_last(xc, fxc)
            self.next_submit = 'new_iter'
        else:
            self.next_submit = 'submit_shrink'

    @submit_method(next_update='update_inside_contraction')
    def submit_inside_contraction(self):
        self._logger.report('Submitting inside contraction step.')
        xcc = ((1 - PSI) * self.xbar + PSI * self.simplex[-1])
        return [self._to_input_list(xcc)]

    @update_method()
    def update_inside_contraction(self, outputs):
        """
        Retrieve the results of an inside contraction step.
        """
        xcc, fxcc = self._get_single_result(outputs)
        if fxcc < self.fun_simplex[-1]:
            self._update_last(xcc, fxcc)
            self.next_submit = 'new_iter'
        else:
            self.next_submit = 'submit_shrink'

    @submit_method(next_update='update_shrink')
    def submit_shrink(self):  # pylint: disable=missing-docstring
        self._logger.report('Submitting shrink step.')
        self.simplex[1:] = self.simplex[0] + SIGMA * (self.simplex[1:] - self.simplex[0])
        self.fun_simplex[1:] = np.nan
        return [self._to_input_list(x) for x in self.simplex[1:]]

    @update_method(next_submit='new_iter')
    def update_shrink(self, outputs):
        self.fun_simplex[1:] = self._get_values(outputs)

    @property
    def _state(self):
        return {k: v for k, v in self.__dict__.items() if k not in ['_result_mapping', '_logger']}

    @property
    def is_finished(self):
        return self.finished

    def _create_inputs(self):
        return getattr(self, self.next_submit)()

    def _update(self, outputs):
        getattr(self, self.next_update)(outputs)

    @property
    def result_value(self):
        _, value = self._get_optimal_result()
        assert value.value == self.fun_simplex[0]
        return value

    @property
    def result_index(self):
        index, _ = self._get_optimal_result()
        return index

    def _get_optimal_result(self):
        """
        Return the index and optimization value of the best evaluation process.
        """
        cost_values = {k: v.output[self.result_key] for k, v in self._result_mapping.items()}
        return min(cost_values.items(), key=lambda item: item[1].value)


@export
class NelderMead(OptimizationEngineWrapper):
    """
    Engine to perform the Nelder-Mead (downhill simplex) method.

    :param simplex: The current / initial simplex. Must be of shape (N + 1, N), where N is the dimension of the problem.
    :type simplex: array

    :param fun_simplex: Function values at the simplex positions.
    :type fun_simplex: array

    :param xtol: Tolerance for the input x.
    :type xtol: float

    :param ftol: Tolerance for the function value.
    :type ftol: float

    :param max_iter: Maximum number of iteration steps.
    :type max_iter: int

    :param input_key: Name of the input argument in the evaluation process.
    :type input_key: str

    :param result_key: Name of the output argument in the evaluation process.
    :type result_key: str
    """
    _IMPL_CLASS = _NelderMeadImpl

    def __new__(  # pylint: disable=arguments-differ,too-many-arguments
        cls,
        simplex,
        fun_simplex=None,
        xtol=1e-4,
        ftol=1e-4,
        max_iter=1000,
        input_key='x',
        result_key='result',
        logger=None
    ):
        return cls._IMPL_CLASS(
            simplex=simplex,
            fun_simplex=fun_simplex,
            xtol=xtol,
            ftol=ftol,
            max_iter=max_iter,
            input_key=input_key,
            result_key=result_key,
            logger=logger
        )
