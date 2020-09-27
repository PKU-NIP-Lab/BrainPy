# -*- coding: utf-8 -*-

import inspect
from .. import _numpy as bnp
from .. import profile
from ..utils import helper
from collections import OrderedDict


class ModelDefError(Exception):
    pass

_neu_no = 0
_syn_no = 0


class BaseType(object):
    def __init__(self, create_func, name=None, type_='neu'):
        # name
        # -----
        if name is None:
            if type_ == 'neu':
                global _neu_no
                self.name = f'NeuGroup{_neu_no}'
                _neu_no += 1
            elif type_ == 'syn':
                global _syn_no
                self.name = f'SynGroup{_syn_no}'
                _syn_no += 1
            else:
                raise KeyError('Unknown group type: ', type_)
        else:
            self.nam = name

        # create_func
        # ------------
        self.create_func = create_func

        # check "create_func"
        try:
            func_return = create_func()
        except TypeError as e:
            raise ModelDefError(f'Arguments in "{create_func.__name__}" must provide default values.')

        if not isinstance(func_return, (tuple, list)):
            raise ModelDefError('"create_func" must return a tuple/a_list.')
        for i in range(len(func_return)):
            if i == 0 and callable(func_return[0]):
                raise ModelDefError('First return value must be "variables", not a callable.')
            else:
                if not callable(func_return[0]):
                    raise ModelDefError('Non-first return values must be callable functions.')

        # parameters
        # ------------
        parameters = inspect.getcallargs(create_func)
        self.parameters = parameters

        # update functions
        # ------------------
        self.update_functions = func_return[1:]

        # variables
        # ----------
        variables = func_return[0]
        if variables is None:
            variables = OrderedDict()
        elif isinstance(variables, (list, tuple)):
            variables = OrderedDict((var_, 0.) for var_ in variables)
        elif isinstance(variables, dict):
            variables = OrderedDict(variables)
        else:
            raise ValueError('Unknown variables type: {}'.format(type(variables)))

        if type_ == 'neu':
            variables['not_ref'] = 1.
            variables['above_th'] = 0.
            variables['spike'] = 0.
            variables['sp_time'] = -1e7
            variables['input'] = 0.
        self.variables = variables

    def __str__(self):
        return f'{self.nam} (Abstract)'







class NodeGroup2(object):
    pars = dict()
    vars = dict()
    update = None
    name = None

    __slots__ = ('num', 'var2index', 'state', 'S', 'P', '_mon_vars', 'mon')

    def __init__(self, vars_init=None, pars_updates=None):
        # variables and "state" ("S")
        # ----------------------------
        assert isinstance(vars_init, dict), '"vars_init" must be a dict.'
        for k, v in vars_init:
            if k not in self.vars:
                raise KeyError('variable "{}" is not defined in "{}".'.format(k, self.name))
            self.vars[k] = v

        if profile.is_numba_bk():
            import numba as nb

            self.var2index = dict()
            self.state = bnp.zeros((len(self.vars), self.num), dtype=bnp.float_)
            for i, (k, v) in enumerate(self.vars.items()):
                self.state[i] = v
                self.var2index[k] = i
        else:
            self.var2index = None
            self.state = dict()
            for k, v in self.vars.items():
                self.state[k] = bnp.ones(self.num, dtype=bnp.float_) * v
        self.S = self.state

        # parameters and "P"
        # -------------------
        assert isinstance(pars_updates, dict), '"pars_updates" must be a dict.'
        for k, v in pars_updates:
            val_size = bnp.size(v)
            if val_size != 1:
                if val_size != self.num:
                    raise ValueError('The size of parameter "{k}" is wrong, "{s}" != 1 and '
                                     '"{s}" != group.num.'.format(k=k, s=val_size))
            self.pars[k] = v

        if profile.is_numba_bk():
            max_size = bnp.max([bnp.size(v) for v in self.pars.values()])
            if max_size > 1:
                self.P = nb.typed.Dict(key_type=nb.types.unicode_type, value_type=nb.types.float64[:])
                for k, v in self.pars.items():
                    self.P[k] = bnp.ones(self.num, dtype=bnp.float_) * v
            else:
                self.P = nb.typed.Dict(key_type=nb.types.unicode_type, value_type=nb.types.float64)
                for k, v in self.pars.items():
                    self.P[k] = v
        else:
            self.P = self.pars

        # update_func
        # ----------------------
        if profile.is_numba_bk():
            self.update = numbify_func(self.update)

    def set_var(self, var, value):
        """Set the variable state.

        Parameters
        ----------
        var : str
            The variable name.
        value : bnp.ndarray
            The value to set for the variable.
        """
        # check variable name
        if var not in self.vars:
            raise KeyError(f'variable "{var}" is not defined in "{self.name}".')

        # check value size
        val_size = bnp.size(value)
        if val_size != 1:
            if val_size != self.num:
                raise ValueError('The size of variable "{k}" is wrong, "{s}" != 1 and '
                                 '"{s}" != group.num'.format(k=var, s=val_size))

        # set value
        if profile.is_numba_bk():
            self.state[self.var2index[var]] = value
        else:
            self.state[var] = value

    def get_var(self, var):
        """Get the variable state.

        Parameters
        ----------
        var : str
            The name of the variable.

        Returns
        -------
        value : bnp.ndarray
            The current value of the variable.
        """
        if profile.is_numba_bk():
            return self.state[self.var2index[var]]
        else:
            return self.state[var]

    def init_monitor(self, length):
        """Initialize monitor state.

        Parameters
        ----------
        length : int
            The total running length.
        """
        for k in self._mon_vars:
            self.mon[k] = bnp.zeros((length, self.num), dtype=bnp.float_)




def judge_spike(t, vth, S, k):
    """Judge and record the spikes of the given neuron group.

    Parameters
    ----------
    t : float
        The current time point.
    vth : int, float, bnp.ndarray
        Threshold to judge spike.
    S : bnp.ndarray
        The state of the neuron group.
    k : str
        The variable for spike judgement.

    Returns
    -------
    spike_indexes : list
        The neuron indexes that are spiking.
    """
    reach_threshold = (S[k] >= vth).astype(bnp.float_)
    spike_st = reach_threshold * (1. - S['above_th'])
    spike_idx = bnp.where(spike_st > 0.)[0]
    S['reach_th'] = reach_threshold
    S['spike'] = spike_st
    S['sp_time'][spike_idx] = t
    return spike_idx


def numbify_spike_judger(func):
    pass


def numbify_func(func):
    pass
