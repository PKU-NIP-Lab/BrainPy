import sympy as sp

from npbrain.integrator.sympytools import sympy_to_str, str_to_sympy
from npbrain.integrator.base import StateUpdateMethod
from npbrain.integrator.base import EquationError
from npbrain.integrator.base import extract_method_options

__all__ = ['exponential_euler']


def get_conditionally_linear_system(eqs, variables=None):
    """
    Convert equations into a linear system using sympy.
    
    Parameters
    ----------
    eqs : `Equations`
        The model equations.
    
    Returns
    -------
    coefficients : dict of (sympy expression, sympy expression) tuples
        For every variable x, a tuple (M, B) containing the coefficients M and
        B (as sympy expressions) for M * x + B
    
    Raises
    ------
    ValueError
        If one of the equations cannot be converted into a M * x + B form.

    Examples
    --------
    >>> eqs = Equations('''
    ... dv/dt = (-v + w**2) / tau : 1
    ... dw/dt = -w / tau : 1
    ... ''')
    >>> system = get_conditionally_linear_system(eqs)
    >>> print(system['v'])
    (-1/tau, w**2.0/tau)
    >>> print(system['w'])
    (-1/tau, 0)

    """
    diff_eqs = eqs.get_substituted_expressions(variables)

    coefficients = {}
    for name, expr in diff_eqs:
        var = sp.Symbol(name, real=True)
        s_expr = str_to_sympy(expr.code, variables).expand()
        if s_expr.has(var):
            s_expr = sp.collect(s_expr, var, evaluate=False)
            if len(s_expr) > 2 or var not in s_expr:
                raise ValueError(f'The expression "{expr}", defining the variable {name}, '
                                 f'could not be separated into linear components')
            coefficients[name] = (s_expr[var], s_expr.get(1, 0))
        else:
            coefficients[name] = (0, s_expr)

    return coefficients


class ExponentialEulerStateUpdater(StateUpdateMethod):
    """
    A state updater for conditionally linear equations, i.e. equations where
    each variable only depends linearly on itself (but possibly non-linearly
    on other variables). Typical Hodgkin-Huxley equations fall into this
    category, it is therefore the default integrator method used in the
    GENESIS simulator, for example.
    """

    def __call__(self, equations, variables=None, method_options=None):
        method_options = extract_method_options(method_options, {})
        if equations.is_stochastic:
            raise EquationError('Cannot solve stochastic '
                                                'equations with this state '
                                                'updater.')

        # Try whether the equations are conditionally linear
        system = get_conditionally_linear_system(equations, variables)

        code = []
        for var, (A, B) in system.items():
            s_var = sp.Symbol(var)
            s_dt = sp.Symbol('dt')
            if A == 0:
                update_expression = s_var + s_dt * B
            elif B != 0:
                BA = B / A
                # Avoid calculating B/A twice
                BA_name = '_BA_' + var
                s_BA = sp.Symbol(BA_name)
                code += [BA_name + ' = ' + sympy_to_str(BA)]
                update_expression = (s_var + s_BA) * sp.exp(A * s_dt) - s_BA
            else:
                update_expression = s_var * sp.exp(A * s_dt)

            # The actual update step
            update = f'_{var} = {sympy_to_str(update_expression)}'
            code.append(update)

        # Replace all the variables with their updated value
        for var in system:
            code += ['{var} = _{var}'.format(var=var)]

        return '\n'.join(code)

    # Copy doc from parent class
    __call__.__doc__ = StateUpdateMethod.__call__.__doc__


exponential_euler = ExponentialEulerStateUpdater()

if __name__ == '__main__':
    pass
    # get linear part
    # ---------------
    # code = '(-v + v**2 + 3) / tau'
    # var = sp.Symbol('v', real=True)
    # s_expr = str_to_sympy(code).expand()
    # print(s_expr)
    # s_expr = sp.collect(s_expr, var, evaluate=False)
    # print(type(s_expr))
    # print(s_expr)

    from npbrain.integrator._equations import Equations
    eqs = Equations("""
        alpha = 0.1 * (V + 40) / (1 - np.exp(-(V + 40) / 10)) : 1
        beta = 4.0 * np.exp(-(V + 65) / 18) : 1
        dm/dt = alpha * (1 - m) - beta * m : 1
    """)
    print(exponential_euler(eqs))