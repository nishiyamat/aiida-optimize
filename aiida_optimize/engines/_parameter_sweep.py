"""
Defines a parameter sweep optimization engine.
"""

from __future__ import division, print_function, unicode_literals

from fsc.export import export

from aiida.orm.data import to_aiida_type

from ._base import OptimizationEngine


@export
class ParameterSweep(OptimizationEngine):
    """
    TODO
    """

    def __init__(self, parameters, result_key='cost_value', result_state=None):
        super(ParameterSweep, self).__init__(result_state=result_state)
        self._parameters = parameters
        self._result_key = result_key

    @property
    def _state(self):
        return {'parameters': self._parameters, 'result_key': self._result_key}

    @property
    def is_finished(self):
        if len(self._result_mapping) < len(self._parameters):
            return False
        return not any(
            res.output is None for res in self._result_mapping.values()
        )

    def _create_inputs(self):
        return [{k: to_aiida_type(v)
                 for k, v in param_dict.items()}
                for param_dict in self._parameters]

    def _update(self, outputs):
        pass

    @property
    def result_value(self):
        _, value = self._get_optimal_result()
        return value

    @property
    def result_index(self):
        index, _ = self._get_optimal_result()
        return index

    def _get_optimal_result(self):
        """
        Return the index and optimizatin value of the best calculation workflow.
        """
        cost_values = {
            k: v.output[self._result_key]
            for k, v in self._result_mapping.items()
        }
        return min(cost_values.items(), key=lambda item: item[1].value)
