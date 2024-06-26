# -*- coding: utf-8 -*-
# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: ExecuteTime,collapsed,jupyter,tags,code_folding,-autoscroll
#     formats: ipynb,py:light
#     notebook_metadata_filter: all,-widgets,-varInspector
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.14.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
#   language_info:
#     codemirror_mode:
#       name: ipython
#       version: 3
#     file_extension: .py
#     mimetype: text/x-python
#     name: python
#     nbconvert_exporter: python
#     pygments_lexer: ipython3
#     version: 3.9.16
# ---

# # Solution Methods for Microeconomic Dynamic Stochastic Optimization Problems (MicroDSOP)
#
# - Author: Tao Wang and Chris Carroll (as of Feb 2022)
#
# This notebook reproduces all the figures (except for those associated with the "method of moderation") in Chris's Carroll's [SolvingMicroDSOP lecture notes](https://llorracc.github.io/SolvingMicroDSOPs/).
#
# The purpose here is to mirror the results from the original lecture notes as closely as possible. Therefore, the notebook contains a stand-alone chunk of code specific to the content of each section in the paper.

# ### Some Python-related specifics: import necessary classes
#
# The implementation takes advantage of Python's ability to bundle parameters with functionality via its object-oriented framework. We will import classes for CRRA utility, a class that discretes approximation to continuous distributions, and the "gothic" class that encapsulates functions $\mathfrak{v}$, $\mathfrak{v}'$, $\mathfrak{c}$, which all involve expectations.
#
# - The `utility` function class allows us to create an instance of a utility function, setting the risk aversion parameter once, and has a convenient "prime" method which executes the first derivative.
#
# - `DiscreteApproximation` fully implements an instance of the discrete approximation to a continuous distribution, taking advantage of SciPy's "frozen distribution" framework. It has a convenient way of calculating the expected value of any defined function of the random variable.
#
# - The `Gothic` class is bundled with methods that execute $\mathfrak{v}$, $\mathfrak{v}'$, $\mathfrak{c}$, and interpolations of each. They all involve calculating expectations of utility/marginal utility/value/marginal value, which will loop over discretized values of the income shock.

# +
from copy import copy

# First import all necessary libraries.
import numpy as np  # Import Python's numeric library as an easier-to-use abbreviation, "np"
import pylab as plt  # Import Python's plotting library as the abbreviation "plt"
import scipy.stats as stats  # Import Scientific Python's statistics library
from numpy import log, exp  # for cleaner-looking code below
from scipy.interpolate import InterpolatedUnivariateSpline
from scipy.optimize import brentq as scipy_find_root  # Import the brentq root-finder
from scipy.optimize import minimize as scipy_minimize

from Code.Python.resources import (
    Utility,
    DiscreteApproximation,
    DiscreteApproximationTwoIndependentDistribs,
)

## notice that the resources directory is stored in the subfolder Code/Python.
## It can be imported only if there is an __init__.py file in that folder

import warnings

warnings.filterwarnings("ignore", category=UserWarning)
## the user warning is surpressed for a cleaner presentation.
# -

### for comparison purposes
## import some modules from HARK libararies
from HARK.ConsumptionSaving.ConsIndShockModel import init_lifecycle
from HARK.ConsumptionSaving.ConsPortfolioModel import (
    PortfolioConsumerType,
)

# ## 0. Define Parameters, Grids, Utility Function
# Set up general parameters, as well as the first two major class instances: the utility function and the discrete approximation.

# + code_folding=[]
# Set up general parameters:

rho = 2.0  ### relative risk aversion coefficient
beta = 0.96  ### discount factor
PermGroFac = np.array([1.0])  # permanent income growth factor
# A one-element "time series" array
# (the array structure needed for gothic class below)
R = 1.02  ## Risk free interest factor

# Define utility:
u = Utility(rho)
# -


# ## 1. Discretization of the Income Shock Distribution
#
# We assume that the transitory shock to income is lognormally distributed,
#
# \begin{align}
# \theta & \sim \mathcal{N}(-\theta^{2}/2,\theta^{2})
# \end{align}
#
# and we approximate it by an equiprobable discretization.
#
# - See detailed discussion [here](https://llorracc.github.io/SolvingMicroDSOPs/#Discretizing-the-Distribution)
#

# + code_folding=[]
# Create a discrete approximation instance:

theta_sigma = 0.5
theta_mu = -0.5 * (theta_sigma**2)
theta_z = stats.lognorm(
    theta_sigma, 0, np.exp(theta_mu)
)  # Create "frozen" distribution instance
theta_grid_N = (
    7  ### how many grid points to use approximate this continuous distribution
)

theta = DiscreteApproximation(
    N=theta_grid_N, cdf=theta_z.cdf, pdf=theta_z.pdf, invcdf=theta_z.ppf
)

# Retrieve the values and the probabilities and show that their dot product is approximately 1.0
theta_vals = theta.X
theta_prob = theta.pmf
theta_expected = np.dot(theta_vals, theta_prob)
print("theta_expected = ", theta_expected)


# + code_folding=[]
#############################
## Figure 1
############################

x_min = theta_mu
x0 = 0.0
x1 = 4.0

theta.plot(x0, x1)

print(
    "The distance between two adjacent horizontal dash lines represent the equiprobable bin."
)


# +
## Other parameters

# Self-imposed lower bounds(for period T)
# the minimum asset (the maximum debt) is the discounted value of lowest possible transitory income shock
## the so called "natural borrowing constraint"

self_a_min = -min(theta.X) * PermGroFac[0] / R  # self-imposed minimum a
# -


# ## A Gothic Class
#
#
# The main code used to implement the solution can be found in the "Gothic" class definition, which contains methods implementing the $\mathfrak{v}$, $\grave{\mathfrak{v}}$  (linear interpolation of $\mathfrak{v}$), $\mathfrak{v}'$, $\grave{\mathfrak{v}}'$, and $\mathfrak{c}$, $\grave{\mathfrak{c}}'$ functions. These are essentially expected value, expected marginal value, and expected marginal utility, respectively, as functions of next-period value and consumption policy functions.
#
# Since these functions all involve computing expectations, we bundle them together as a Gothic class and use an instance of the class below to solve a consumption function; this mirrors the content from [Discretizing-the-Distribution](llorracc.github.io/SolvingMicroDSOPs#Discretizing-the-Distribution) to [Improving-the-a-Grid](llorracc.github.io/SolvingMicroDSOPs#Improving-the-a-Grid) in the [lecture notes](https://llorracc.github.io/SolvingMicroDSOPs/).
#

# #### Import and create instance of the "Gothic" class
#
# Create a particular instance of the `gothic` class, using $u$, $\beta$, $\rho$, $\Gamma$, and the $\theta$-approximation.

# +
from Code.Python.gothic_class import Gothic

gothic = Gothic(u, beta, rho, PermGroFac, R, theta)
# -


# ## 2. Solving the Model by Value Function Maximization
#
# - See detailed discussion [beginning here](https://llorracc.github.io/SolvingMicroDSOPs#Solving-the-Next-To-Last-Period)

# First, we numerically maximize the value function over a very fine set of gridpoints of market resources (m) to get the benchmark solution to the consumption policy function and value function. We use this to represent the "accurate" solution in this notebook.
#
# This approach will be improved in different ways in the sections below.

# Boundaries for the plot
m_min, m_max, m_size = 0, 4.0, 5


# + code_folding=[]
### solve the model with very fine mVec_fine

cVec = []  # Start with an empty list. Lists can hold any Python object.
vVec = []  # Empty list for values

## fine grid of m
mVec_fine = np.linspace(m_min, m_max, 100)

for m in mVec_fine:
    c_max = m + PermGroFac[0] * theta.X[0] / R  ## spend everything for the given X

    ## Define the a one-line (negative) value function of the T-1 period
    def neg_value(c):
        return -(u(c) + gothic.V(m - c))

    ## negative value to be minimized
    ## using the scipy.optimize.minimize tool we imported as scipy_minimize
    ## notice here V takes market resources at T-1 as input since this is the T-1 period
    ## the consumption policy in the terminal period T is trivial
    ## for this mTm1, find the c that maximizes the value from T-1 and T
    residual = scipy_minimize(
        neg_value,
        np.array([0.3 * m + 0.1]),  ## an initial guess of the c
        method="trust-constr",  ## choose the 'trust-constr' optimization algorithm
        bounds=(
            (1e-12, 0.999 * c_max),
        ),  ## consumption has to be between ~0.0 and c_max
        options={"gtol": 1e-12, "disp": False},
    )
    c = residual["x"][0]  # maximizer of the value
    v = -residual["fun"]  ## value
    cVec.append(c)
    vVec.append(v)


# + code_folding=[]
# Look at the solution

caption = plt.title(r"$c_{T −1}(m_{T-1})$ (solid)")
plt.plot(mVec_fine, cVec, "k-")  ## c(m)
plt.xlabel(r"$m_{T-1}$")
plt.ylabel(r"$c_{T-1}$")
plt.show()
# -


# Then, solve the model with only a small number of grid points of m.

# +
# very sparse m_grid

mVec = np.linspace(m_min, m_max, m_size)
print("solving at the points", mVec)


# + code_folding=[]
cVec0 = []  # Start with empty list. Lists can hold any Python object.
vVec0 = []

for m in mVec:
    c_max = m + PermGroFac[0] * theta.X[0] / R

    def nvalue(c):
        return -(
            u(c) + gothic.V(m - c)
        )  # Define the a one-line value function of the T-1 period

    res = scipy_minimize(
        nvalue,
        np.array([0.2 * m + 0.1]),
        method="trust-constr",
        bounds=((1e-12, 0.999 * c_max),),
        options={"gtol": 1e-12, "disp": False},
    )
    c = res["x"][0]  # maximizer of the value
    v = -res["fun"]  ## value
    cVec0.append(c)
    vVec0.append(v)

print(
    "Solution obtained for m=", mVec, " is c=", cVec0
)  # Look at the consumption from the list.
# -


# ## 3. An Interpolated Consumption Function
#
# Although we have now solved optimal $c$ above for a finite set of predetermined gridpoints of $m$, how do we know the consumption value at different values of $m$ not among these grid points? We need interpolation.
#
# - See detailed discussion [here](https://llorracc.github.io/SolvingMicroDSOPs/#an-interpolated-consumption-function)
#

# The interpolated consumption function is not very different from the true consumption function. (See Figure 2)

# + code_folding=[]
## interpolated cFunc based on the solution from a small number of m gridpoints

cFunc0 = InterpolatedUnivariateSpline(mVec, cVec0, k=1)
mVec_int = np.linspace(0.0, 4.0, 50)
cVec_int = cFunc0(mVec_int)

######################################
### Figure 2
######################################
plt.plot(mVec_fine, cVec, "k-")  ## c(m)
plt.plot(mVec_int, cVec_int, "--")  ## 'c(m)
plt.xlim(self_a_min, 4.0)
plt.xlabel(r"$m_{T-1}$")
plt.ylabel(r"$c_{T-1}$")
plt.title(r"$c_{T −1}(m_{T-1})$ (solid) versus $\grave c_{T-1}(m_{T-1})$(dashed)")
plt.show()
# -


# It turns out that the interpolated value function only poorly approximates its true counterpart. (See [Figure PlotvTm1Simple](https://llorracc.github.io/SolvingMicroDSOPs#PlotvTm1Simple)). The reason for this is that the value function is highly concave.

# + code_folding=[]
## interpolated v func
vFunc0 = InterpolatedUnivariateSpline(mVec, vVec0, k=1)

vVec_int = vFunc0(mVec_int)

#########################################
### Figure 3
########################################

plt.plot(mVec_fine, vVec, "k-")  ## v(m)
plt.plot(mVec_int, vVec_int, "--")  ## 'v(m)
plt.xlim(self_a_min, 4.0)
plt.xlabel(r"$m_{T-1}$")
plt.ylabel(r"$V_{T-1}$")
plt.title(
    r"$v_{T −1}(m_{T −1})$ (solid) versus interpolated $\grave v_{T-1}(m_{T-1})$ (dashed)"
)
plt.show()
# -


# ## 4. Interpolating Expectations
#
# - See detailed discussion at [Interpolating-Expectations](https://llorracc.github.io/SolvingMicroDSOPs/#Interpolating-Expectations)
#
# The program above turns out to be __inefficient__. For every value of $m_{T −1}$ the program must calculate the utility consequences of various possible choices of $c_{T−1}$ as it searches for the best choice. But for any given value of $m_{T-1}-c_{T-1}=a_{T−1}$, there is a good chance that the program may end up calculating the corresponding v many times while maximizing utility from different $m_{T −1}$’s.
#
# An improvement can be made: we can construct a direct numerical approximation to the value function based on a vector of predefined $a=m-c$ grid and use the interpolated function to calculate $\mathfrak{v}_{T-1}$ for a given $a$.

# + code_folding=[]
# A grid:
a_min, a_max, a_size = 0.0, 4.0, 5
aVec = np.linspace(a_min, a_max, a_size)

## gothic v values for a vector of a
## get the values from a finely constructed a
gothicvVec = np.array([gothic.V(a) for a in aVec])
## then create an interpolation of that to use in solving the models
gothicvFunc0 = InterpolatedUnivariateSpline(
    aVec, gothicvVec, k=1
)  ## this is the interpolated gothic v func

## solve the model again

cVec1 = []  # Start with empty list. Lists can hold any Python object.
vVec1 = []

for m in mVec:
    c_max = m + PermGroFac[0] * theta.X[0] / R

    ## Below, instead of using gothic.V func, we use the interpolated gothicvFun
    def nvalue(c):
        return -(u(c) + gothicvFunc0(m - c))

    ##################################################################################################
    #### Notice here, instead of drawing Gothic.V function, we use the interpolation of it gothicvFunc0
    ###################################################################################################

    residual = scipy_minimize(
        nvalue,
        np.array([0.3 * m + 0.1]),
        method="trust-constr",
        bounds=((1e-12, 0.999 * c_max),),
        options={"gtol": 1e-12, "disp": False},
    )
    c = residual["x"][0]  # maximizer of the value
    v = -residual["fun"]  ## value
    cVec1.append(c)
    vVec1.append(v)

print("Our new solution for m=", mVec, " is cVec1=", cVec1)
# -


# The interpolated functions are of course identical at the gridpoints chosen for $a_{T− 1}$ and even in the interpolated areas they appear reasonably close except in the region below $m_{T −1} = 1.0$. (See [this Figure](https://llorracc.github.io/#PlotOTm1RawVSInt))

# + code_folding=[]
#################
### Figure 4
#################
### get real gothic v
aVec_fine = np.linspace(a_min, a_max, 100)
gothicvVec_fine = np.array([gothic.V(a) for a in aVec_fine])

# plt.plot(mVec,vVec1,'-.')
plt.rc("font", size=12)

plt.plot(aVec_fine, gothicvVec_fine, "k-")
plt.plot(aVec, gothicvVec, "--")
plt.xlabel(r"$a_{T-1}$")  ### this is different from lecture note
plt.ylabel(r"$\mathfrak{v}_{T-1}$")
plt.title(
    r"End of period value $\mathfrak{V}_{T^{+}-1}}}(a_{T-1})$ (solid) vs $\grave \mathfrak{V}_{T-1}(a_{T-1})$ (dashed)"
)
plt.show()
# -


# Nevertheless, the resulting consumption rule obtained when $\grave{\mathfrak{v}}_{T-1}(a_{T-1})$ is used instead of $\mathfrak{v}_{T −1}(a_{T−1})$  is surprisingly bad. (See Figure 5)

# +
####################
### Figure 5
####################

plt.plot(mVec_fine, cVec, "k-")
plt.plot(mVec, cVec1, "--")
plt.xlabel(r"$m_{T-1}$")
plt.ylabel(r"$c_{T-1}$")
plt.title(r"$c_{T-1}(m_{T-1})$ (solid) versus $\grave c_{T-1}(m_{T-1})$ (dashed)")
# -


# ## 5. Value Function versus the First Order Condition
#
# - See more detailed discussion [here](https://llorracc.github.io/SolvingMicroDSOPs/#Value-Function-versus-First-Order-Condition)
#
# Our difficulty is caused by the fact that consumption choice is governed by the marginal value function, not by the level of the value function (which is what we tried to approximate).
#
# This leads us to an improved approach to solving consumption policy by working with marginal utility/values that come the first-order conditions (FOC). For every exogenously set m grid, we can find the solution to the FOC.
#
# \begin{equation}
# u^{\prime}(c_{T-1}(m_{T-1})) = \mathfrak{v}^{\prime}(m_{T-1}-c_{T-1}(m_{T-1}))
# \end{equation}

# +
##########################
### Figure PlotuPrimeVSOPrime (omitted here)
##########################

# u′(c) versus v′_{T −1}(3 − c), v′_{T −1}(4 − c), v`′_{T −1}(3 − c), v`′_{T −1}(4 − c)
# -


# Now we solve for consumption using the FOCs instead of value function maximization.

# +
cVec2 = []  # Start with empty list.
for m in mVec:
    mintotwealth = m + PermGroFac[0] * theta.X[0] / R

    def foc_condition(c):
        return u.prime(c) - gothic.VP_Tminus1(
            m - c
        )  # Define the a one-line function for the FOC

    c = scipy_find_root(
        foc_condition, 1e-12, 0.999 * mintotwealth
    )  # Zero-find on the FOC
    cVec2.append(c)

print(cVec2)  # Look at the consumption from the list.
# -


# The linear interpolating approximation looks roughly as good (or bad) for the marginal value function as it was for the level of the value function.

# + code_folding=[]
########################
## Figure PlotOPRawVSFOC
########################


# get the VP for fine grids of a

aVec_fine = np.linspace(0.0001, 4, 1000)
vpVec_fine = [gothic.VP_Tminus1(a) for a in aVec_fine]

# Examine the interpolated GothicVP function:
vpVec = [gothic.VP_Tminus1(a) for a in aVec]

## this is the interpolated gothic v func
gothicvpFunc = InterpolatedUnivariateSpline(aVec, vpVec, k=1)

plt.plot(aVec_fine, vpVec_fine, "k-")  ## gothic v'(a)
plt.plot(aVec, gothicvpFunc(aVec), "--")  ## 'gothic v'(a)
plt.ylim(0.0, 1.0)
plt.xlabel(r"$a_{T-1}$")
plt.ylabel(r"$\mathfrak{v}^{\prime}_{T-1}$")
plt.title(
    r"$\mathfrak{v}^{\prime}(a_{T-1})$ (solid) and $\grave \mathfrak{v}^{\prime}(a_{T-1})$ (dashed)"
)
plt.show()
# -


# The new consumption function (long dashes) is a considerably better approximation of the true consumption function (solid) than was the consumption function obtained by approximating the level of the value function (short dashes). (See Figure 8).

# + code_folding=[]
#########################
## Figure 8
########################

plt.plot(mVec_fine, cVec, "k-", label=r"$c_{T-1}(m_{T-1})$")  ## real c func
plt.plot(
    mVec, cVec1, "-.", label=r"$\grave c_{T-1}(m_{T-1})$ via $\mathfrak{v}$"
)  ## interpolated c func based on interpolated level of value
plt.plot(
    mVec,
    cVec2,
    "r--",
    label=r"$\grave \grave c_{T-1}(m_{T-1})$ via $\mathfrak{v}^{\prime}$",
)  ## interpolated c func based on interpolated marginal value
plt.xlabel(r"$m_{T-1}$")
plt.ylabel(r"$c_{T-1}$")
plt.title(
    r"$c_{T-1}(m_{T-1})$ (solid) versus two methods of constructing $\grave c_{T-1}(m_{T-1})$"
)
plt.legend(loc=4)
# -


# ## 6. Transformation
#
# - See more detailed discussion [here](https://llorracc.github.io/SolvingMicroDSOPs/#Transformation)
#
#
# However, even the new-and-improved consumption function diverges from the true solution, especially at lower values of m. That is because the linear interpolation does an increasingly poor job of capturing the nonlinearity of $v′_{T −1}(a_{T −1})$ at lower and lower levels of a.

# +
cVec3 = []
cVec4 = []

for a in aVec:
    c = gothic.C_Tminus1(a)
    cVec3.append(c)

for a in aVec_fine:
    c = gothic.VP_Tminus1(a) ** (-1 / rho)
    cVec4.append(c)
# -


# ## 7. The Self-Imposed ‘Natural’ Borrowing Constraint and the $a_{T−1}$ Lower Bound
#
# - See more detailed discussion [here](https://llorracc.github.io/SolvingMicroDSOPs/#The-Self-Imposed-Natural-Borrowing-Constraint-and-the-a-Lower-Bound)
#
# As the marginal utility from zero consumption goes to infinity, the agents will try to have at least a little of consumption in the "worst" case. This cutting-edge case happens when the $a_{T-1}$ is exactly equal to the present value of the worst possible transitory shock. As a result, there is a self-imposed borrowing constraint, i.e. a lower bound for the value of $a_{T-1}$.
#
# In general, preset grids of a may not necessarily include this point. We hence insert this self-imposed bound to the beginning of the list of grid to make sure the consumption policy close to this bound is correctly interpolated.

# + code_folding=[]
## Augment the mVec and cVec with one point with bottom

aVecBot = np.insert(aVec, 0, self_a_min)
cVec3Bot = np.insert(cVec3, 0, 0.0)

aVecBot_fine = np.insert(aVec_fine, 0, self_a_min)
cVec4Bot = np.insert(cVec4, 0, 0.0)
# -


# This ﬁgure well illustrates the value of the transformation (Section 6): The true function is close to linear, and so the linear approximation is almost indistinguishable from the true function except at the very lowest values of $a_{T−1}$. (See Figure 9)

# + code_folding=[]
##############
## Figure 9
##############


plt.plot(
    aVecBot_fine,
    cVec4Bot,
    "k-",
    label=r"$(\mathfrak{v}^{\prime}_{T-1}(a_{T-1}))^{-1/\rho}$",
)
plt.plot(aVecBot, cVec3Bot, "--", label=r"$\grave c_{T-1}$")
plt.xlabel(r"$a_{T-1}$")
plt.ylabel(r"$\mathfrak{c}_{T-1}$")
plt.ylim(0.0, 5.0)
plt.vlines(0.0, 0.0, 5.0, "k", "-.")
plt.title(
    r"$\mathfrak{c}_{T-1}(a_{T-1})$ (solid) versus $\grave \mathfrak{c}_{T-1}(a_{T-1})$"
)
plt.legend(loc=4)


# +
## compute gothic_v' as c^(-rho)


def vpVec_fromc(a):
    return InterpolatedUnivariateSpline(aVecBot, cVec3Bot, k=1)(a) ** (-rho)


# -


# And when we calculate $\grave{\grave{\mathfrak{v}}}^{\prime}_{T-1}(a_{T−1})$ as $[\grave{\mathfrak{c}}_{T-1}(a_{T-1})]^{-\rho}$  (dashed line) we obtain a much closer approximation of $\mathfrak{v}^{\prime}_{T-1}(a_{T-1})$. (See Figure 10)

# +
#############################
## Figure 10
############################

plt.plot(aVec_fine, vpVec_fine, "k-")
plt.plot(aVec_fine, vpVec_fromc(aVec_fine), "--")
plt.xlabel(r"$a_{T-1}$")
plt.ylabel(
    r"$\mathfrak{v}^{\prime}_{T-1},\quad \grave \grave \mathfrak{v}^{\prime}_{T-1}$"
)
plt.title(
    r"$\mathfrak{v}^{\prime}_{T-1}(a_{T-1})$ (solid) versus $\grave \grave \mathfrak{v}^{\prime}(a_{T-1})$"
    + "\n constructed using $\grave \mathfrak{c}_{T-1}$ (dashed)"
)
plt.show()
# -


# ## 8. Endogenous Gridpoints: Use Algebra to Find $c_{T-1}(m_{T-1})$
#
# - See more detailed discussion [here](https://llorracc.github.io/SolvingMicroDSOPs/#The-Method-of-Endogenous-Gridpoints)
#
# We now take advantage of the fact that
#
# $$m_{T−1,i} = c_{T−1,i} + a_{T−1,i}\;\;\forall a_{i} \in \mathbb{A}_{grid},$$
#
# to find optimal consumption as a function of $m$, once we have the optimizing choice and $a$ in hand.
#
#

# + code_folding=[0]
# Create the first point in the consumption function:
mVec_egm = [self_a_min]  ## consumption is zero therefore a = m here
cVec_egm = [0.0]

for a in aVec:
    c = gothic.C_Tminus1(a)
    m = c + a
    cVec_egm.append(c)
    mVec_egm.append(m)

# Set up the interpolation:
cFunc_egm = InterpolatedUnivariateSpline(mVec_egm, cVec_egm, k=1)
# -


# Compared to the approximate consumption functions illustrated in Figure 8 $\grave c_{T-1}$ is quite close to the actual consumption function. (See Figure 11)

# + code_folding=[]
####################
## Figure 11 ####
####################


# Plot the first consumption function (c_{T-1}). We will plot the rest in the loop below.
# plt.plot(mVec_egm, mVec_egm, color='0.7')    # Gray 45 deg line
# plot_m_max = 5.0                               # Max plotting point.
# plot_c_max = cFunc_egm(plot_m_max)
temp_c_values = cFunc_egm(mVec_egm)

plt.plot(mVec_fine, cVec, "k-")
plt.plot(mVec_egm, temp_c_values, "--")
plt.xlim(self_a_min, 4.0)
plt.ylim(0.0, 3.0)
plt.xlabel(r"$m_{T-1}$")
plt.ylabel(r"${c}_{T-1}(m_{T-1})$")
plt.title(r"$c_{T-1}(m_{T-1})$ (solid) versus $\grave c_{T-1}(m_{T-1})$ using EGM")
# -


# ## 9. Improve the $\mathbb{A}_{grid}$
#
# - See more detailed discussion [here](https://llorracc.github.io/SolvingMicroDSOPs/#Improving-the-a-Grid)
#
# We will improve our $\mathbb{A}_{grid}.$
#
# We use a multi-exponential growth rate (that is $e^{e^{e^{...}}}$ for some number of exponentiations n) from each point to the next point is constant (instead of, as previously, imposing constancy of the absolute gap between points).

# + code_folding=[2]
### This function creates multiple-exp a_grid


def setup_grids_expMult(minval, maxval, size, timestonest=20):
    i = 1
    gMaxNested = maxval
    while i <= timestonest:
        gMaxNested = np.log(gMaxNested + 1)
        i += 1

    index = gMaxNested / float(size)

    point = gMaxNested
    points = np.empty(size)
    for j in range(1, size + 1):
        points[size - j] = np.exp(point) - 1
        point = point - index
        for i in range(2, timestonest + 1):
            points[size - j] = np.exp(points[size - j]) - 1
    a_grid = points
    return a_grid


# + code_folding=[]
def set_up_improved_EEE_a_grid(minval, maxval, size):
    gMinMin = 0.01 * minval
    gMaxMax = 10 * maxval
    gridMin = log(1 + log(1 + log(1 + gMaxMax)))
    (log(1 + log(1 + log(1 + gMaxMax))) - log(1 + log(1 + log(1 + gMinMin)))) / size
    index = (
        log(1 + log(1 + log(1 + gMinMin)))
        + (log(1 + log(1 + log(1 + gMaxMax))) - log(1 + log(1 + log(1 + gMinMin))))
        / size
    )
    i = 1
    point = 0
    points = []
    while point < gridMin:
        point = point + index
        points.append(point)
        i += 1

    new_a_grid = exp(exp(exp(points) - 1) - 1) - 1
    return new_a_grid


# +
### create the new grid with multiple exponential approach

a_size_splus = 20  ## just need a little more than 5 to cover the whole range of a well

aVec_eee = setup_grids_expMult(a_min, a_max, a_size_splus)
print(aVec_eee)
# -


# Find the consumption function using the improved grid and exogenous gridpoints, and plot against the earlier versions.

# + code_folding=[]
cVecBot = [0.0]
mVecBot = [self_a_min]  # Use the self-imposed a-min value.

for a in aVec_eee:
    c = gothic.C_Tminus1(a)
    m = c + a
    cVecBot.append(c)
    mVecBot.append(m)

print("a grid:", aVec_eee)
# -


# We can see that the endogenous gridpoints of $m$ naturally "bunch" near the area with the most curvature.
#
# It allows a better characterization of the consumption and marginal values of at small values of $a$ (See Figure 12 and 13).
#
#

# + code_folding=[]
###################
## Figure 12
###################

plt.plot(mVec_fine, cVec, "k-")
plt.plot(mVecBot, cVecBot, "*")
plt.xlim(2 * self_a_min, 4.0)
plt.ylim(-0.1, 3.0)
plt.xlabel(r"$m_{T-1}$")
plt.ylabel(r"${c}_{T-1}(m_{T-1})$")
plt.title(
    r"$c_{T-1}(m_{T-1})$ (solid) versus $\grave c_{T-1}(m_{T-1})$"
    + "\n using EGM and EEE grid of $a$ (star)"
)


# +
##################################
## Figure 13
#################################

vpVec_eee = [gothic.VP_Tminus1(a) for a in aVec_eee]

plt.plot(aVec_fine, vpVec_fine, "k-")
plt.plot(aVec_eee, vpVec_eee, "*")
plt.xlabel(r"$a_{T-1}$")
plt.ylabel(r"$\mathfrak{v}^{\prime}_{T-1}$")
plt.title(
    r"$\mathfrak{v}^{\prime}_{T-1}(a_{T-1})$ (solid) versus $\grave \grave \mathfrak{v}^{\prime}(a_{T-1})$"
    + "\n using EGM with EEE grid of a (star)"
)
# -


# ## 10. Artifical Borrowing Constraint
#
# - See more detailed discussion [here](https://llorracc.github.io/SolvingMicroDSOPs/#Imposing-Artificial-Borrowing-Constraints)
#
# Some applications assume an externally imposed borrowing constraint. For instance, when the external borrowing constraint is exactly zero, it is binding before the self-imposed borrowing constraint takes effect.
#
# This can be easily taken care of by replacing the first point in the m grid with 0 instead of a self-imposed borrowing constraint.

# + code_folding=[0, 11]
## set the bool for constrained to be TRUE

constrained = True

# Create initial consumption function:
cVec_const = [0.0]
mVec_const = [self_a_min]

## now the a_min depends on if artifical borrowing constraint is tighter than the natural one
if constrained and self_a_min < 0:
    mVec_const = [0.0]
for a in aVec_fine:
    c = gothic.C_Tminus1(a)
    m = c + a
    if constrained:
        c = np.minimum(c, m)
    cVec_const.append(c)
    mVec_const.append(m)


# + code_folding=[0]
## set the bool for constrained to be FALSE

constrained = False

# Create initial consumption function:
cVec_uconst = [0.0]
mVec_uconst = [self_a_min]

## now the a_min depends on if artifical borrowing constraint is tighter than the natural one
if constrained and self_a_min < 0:
    mVec_const = [0.0]
for a in aVec_fine:
    c = gothic.C_Tminus1(a)
    m = c + a
    if constrained:
        c = np.minimum(c, m)
    cVec_uconst.append(c)
    mVec_uconst.append(m)
# -


# Not surprisingly, the main difference between the two c functions lies in the area of negative wealth. (See Figure 18)

# + code_folding=[0]
#####################
### Figure 18
#####################

plt.plot(mVec_const, cVec_const, "k-")
plt.plot(mVec_uconst, cVec_uconst, "--")
plt.xlabel(r"$m_{T-1}$")
plt.ylabel(r"$c_{T-1}(m_{T-1})")
plt.ylim(0.0, 5.0)
plt.vlines(0.0, 0.0, 5.0, "k", "-.")
plt.title("Constrained (solid) and Unconstrained Consumption (dashed)")
# -


# ## 11. Solving for $c_t(m_t)$ in Multiple Periods
#
# - See more detailed discussion [here](https://llorracc.github.io/SolvingMicroDSOPs/#x1-210006)
#
# We now employ the recursive nature of the problem to solve all periods. Recall that in general,
#
# $$\mathfrak{v}'(a_{t}) = \mathbb{E}_{t}[\beta \mathrm{R} \PermGroFac^{-\rho} _{t+1} \mathrm{u}' (c _{t+1} (\mathcal{R} _{t+1}a _{t}+\theta _{t+1}))]$$
#
# That is, once we have $c _{t+1} (\mathcal{R} _{t+1}a _{t}+\theta _{t+1})$ in hand, we can solve backwards for the next period, and so on back to the first period.
#
# As with $c_{T-1}$, we will employ the first-order condition
#
# $$u'(c_{t}) = \mathfrak{v}'(m_{t}-c_{t}) = \mathfrak{v}'(a_{t})$$
#
# to obtain our consumption function from $\mathfrak{v}^{'}_{t}(a_t)$.
#
# To get smoothness, we will make a very large "EEE" grid.
#
# We will also use Python's "time" module to time the whole procedure as it executes.
#
#

# +
from time import time

T = 60  # How many periods/consumption functions?
aVec_eee = setup_grids_expMult(
    a_min, a_max, 40
)  # Create a bigger grid, for smoother curve.

self_a_min_life = T * [self_a_min]


# + code_folding=[11, 33]
## to make the solution simpler for life cycle, i.e. no need to update self_a_min every period
constrained = True

##########################################################
# Create initial consumption function for the second to the last period
#########################################################

cVec = [0.0]
mVec = [self_a_min]
if constrained and self_a_min < 0:
    mVec = [0.0]

for a in aVec_eee:
    c = gothic.C_Tminus1(a)
    m = c + a
    if constrained:
        c = np.minimum(c, m)
    cVec.append(c)
    mVec.append(m)

# Set up the interpolation:
cFunc = InterpolatedUnivariateSpline(mVec, cVec, k=1)

## save it in a dictionary
cFunc_life = {T - 1: cFunc}

########################################
## backward iteration over life cycle
########################################

# Loop for all consumption functions in our range:
for t in range(T - 2, -1, -1):
    cVec = [0.0]
    mVec = [self_a_min]
    if constrained and self_a_min < 0:
        mVec = [0.0]
    for a in aVec_eee:
        c = gothic.C_t(
            a, cFunc
        )  ## notice here the c func from previous period is the input !!!
        m = c + a
        if constrained:
            c = np.minimum(c, m)
        cVec.append(c)
        mVec.append(m)

    # Update the consumption function
    cFunc = InterpolatedUnivariateSpline(mVec, cVec, k=1)

    # Save updated function:
    cFunc_life[t] = cFunc


# + code_folding=[]
##############################
#### Figure 19
##############################


for t in range(T - 1, T - 10, -1):
    cFunc = cFunc_life[t]
    cVec_fine = cFunc(mVec_fine)
    plt.plot(mVec_fine, cVec_fine, "k-")

plt.xlabel(r"$m$")
plt.ylabel(r"$\grave c_{T-n}(m)$")
plt.title(r"Convergence of $\grave c_{T-n}(m)$ Functions as $n$ Increases")
# -


# The consumption functions converge as the horizon extends.

# ## 12. Multiple Control Variables (MC)
#
# - See more detailed discussion [here](https://llorracc.github.io/SolvingMicroDSOPs/#Multiple-Control-Variables)
#
# Besides consumption, the new control variable that the consumer can now choose is the portion of the portfolio $\varsigma_t$ to invest in risky assets with a return factor $\mathbf{R}_{t+1}$.  The overall return on the consumer’s portfolio between $t$ and $t + 1$, $\pmb{\mathfrak{R}}_t$, is equal to the following.
#
#
# \begin{equation}
# \pmb{\mathfrak{R}}_t = R + (\mathbf{R}_{t+1}-R) \varsigma_t
# \end{equation}
#
# Now, $\mathfrak{v}_t$ is a function of both $a_{t}$ and the risky asset share $\varsigma_t$.
# We also need to define $\mathfrak{v}^{a}$ and $\mathfrak{v}^{\varsigma}$, the expected marginal value from saving and risky share, respectively.
#
# We can solve the problem sequentially in two separate stages.
#
#  - At the first stage, solve the optimizing share $\varsigma^*$ for a vector of predetermined $a$ relying on the FOC condition associated with $\mathfrak{v}^{\varsigma}$.
#  - At the second stage, use optimal $\varsigma^*$ to construct $\pmb{\mathfrak{R}}$ and solve the consumption exactly in a similar way as before with only one single choice variable.

# Now we need to redefine and add additional Gothic functions for the portfolio choice problem. In the meantime, some elements of the class remain the same. One easy and consistent way of achiving this end is to ''inherit'' the existing Gothic class and superimpose some of the functions with modified ones.

# + code_folding=[6, 32, 64, 96, 99, 115, 117, 128, 143]
## MC stands for multiple controls

## Now the GothicMC takes Distribution as a new input, which
## is a class of two discretized log normal distributions, for income and risky asset return


class GothicMC(Gothic):  ## inheriting from Gothic class
    ## inheritance from Gothic and adds additional functions/methods for portfolio choice
    def __init__(
        self,
        u,
        beta,
        rho,
        PermGroFac,
        R,
        Distribution,
        share_grid_size,
        Income=None,
        Return=None,
        variable_variance=False,
    ):
        super().__init__(u, beta, rho, PermGroFac, R, Income, variable_variance=False)
        ## super(). here initialize the GothicMC class as Gothic does
        self.Return = Return
        self.Distribution = (
            Distribution  ## a class instance of two log normal distributions
        )
        ## x1 is income and x2 is asset return
        ### additional discretized risky asset returns
        self.share_grid_size = share_grid_size
        self.varsigma_grids = np.linspace(0.0, 1.0, self.share_grid_size)

    def varsigma_Tminus1(self, a):
        """
        Optimization of Share on continuous interval [0,1]

        """

        ## make an array storing FOCs for different shares at this value of a
        share_girds = self.varsigma_grids
        FOC_s = np.empty_like(share_girds)
        for j in range(len(share_girds)):
            FOC_s[j] = self.Vsigma_Tminus1(a, share_girds[j])

        ## find the optimal share
        if a < 0:
            varsigma_opt = 0.0
        else:
            if FOC_s[-1] > 0.0:  ## mv of the share=1 is still positive
                varsigma_opt = 1.0
            elif FOC_s[0] < 0.0:  # mv of the share=0 is still negative
                varsigma_opt = 0.0
            else:
                crossing = np.logical_and(FOC_s[1:] <= 0.0, FOC_s[:-1] >= 0.0)
                idx = np.argwhere(crossing)[0]
                bot_s = share_girds[idx]
                top_s = share_girds[idx + 1]
                bot_f = FOC_s[idx]
                top_f = FOC_s[idx + 1]
                alpha = 1.0 - top_f / (top_f - bot_f)
                varsigma_opt = (1.0 - alpha) * bot_s + alpha * top_s
        return np.squeeze(varsigma_opt)

    def varsigma_t(self, a, c_prime):
        ## make an array storing FOCs for different share at this value of a
        share_girds = self.varsigma_grids
        FOC_s = np.empty_like(share_girds)
        for j in range(len(share_girds)):
            FOC_s[j] = self.Vsigma_t(a, share_girds[j], c_prime)

        ## find the optimal share
        if a < 0:
            varsigma_opt = 0.0
        else:
            if FOC_s[-1] > 0.0:  ## mv of the share=1 is still positive
                varsigma_opt = 1.0
            elif FOC_s[0] < 0.0:  # mv of the share=0 is still negative
                varsigma_opt = 0.0
            else:
                crossing = np.logical_and(FOC_s[1:] <= 0.0, FOC_s[:-1] >= 0.0)
                idx = np.argwhere(crossing)[0]
                bot_s = share_girds[idx]
                top_s = share_girds[idx + 1]
                bot_f = FOC_s[idx]
                top_f = FOC_s[idx + 1]
                alpha = 1.0 - top_f / (top_f - bot_f)
                varsigma_opt = (1.0 - alpha) * bot_s + alpha * top_s
        return np.squeeze(varsigma_opt)

    def C_Tminus1(self, a):
        return self.Va_Tminus1(a) ** (-1.0 / self.rho)

    def C_t(self, a, c_prime):
        return self.Va_t(a, c_prime) ** (-1.0 / self.rho)

    def Va_Tminus1(self, a):
        """
        gothic v's first derivative with respect to the a given optimal share varsigma_opt at a
        """
        varsigma_opt = self.varsigma_Tminus1(a)

        ## the g function below computes the gothic v' for a particular realization of risky return and income shock
        def Va_func(tinc_shk, rreturn):
            return (self.R + (rreturn - self.R) * varsigma_opt) * self.u.prime(
                (self.R + (rreturn - self.R) * varsigma_opt) * a / self.Gamma[-1]
                + tinc_shk
            )

        ## the Distribution.E() calculates the expectation of g values over the joint distribution of return and income shock
        GVTm1Pa = self.beta * self.Gamma_to_minusRho[-1] * self.Distribution.E(Va_func)
        return GVTm1Pa

    def Va_t(self, a, c_prime):
        varsigma_opt = self.varsigma_t(a, c_prime)

        def Va_func(tinc_shk, rreturn):
            return (self.R + (rreturn - self.R) * varsigma_opt) * self.u.prime(
                c_prime(
                    (self.R + (rreturn - self.R) * varsigma_opt) * a / self.Gamma[-1]
                    + tinc_shk
                )
            )

        GVtPa = self.beta * self.Gamma_to_minusRho[-1] * self.Distribution.E(Va_func)
        return GVtPa

    def Vsigma_Tminus1(self, a, varsigma):
        """
        gothic v's first derivative with respect to the portfolio share varsigma in the last period
        """
        if a != 0.0:

            def Vshare_func(tinc_shk, rreturn):
                return (rreturn - self.R) * self.u.prime(
                    (self.R + (rreturn - self.R) * varsigma) * a / self.Gamma[-1]
                    + tinc_shk
                )

            # Because next period the consumer spends everything,
            # we substitute
            GVTm1Psigma = (
                self.beta * a / self.Gamma[-1] * self.Distribution.E(Vshare_func)
            )
        else:
            GVTm1Psigma = np.inf
        return GVTm1Psigma

    def Vsigma_t(self, a, varsigma, c_prime):
        """
        gothic v's first derivative with respect to the portfolio share varsigma in all earlier periods
        """
        if a != 0.0:

            def Vshare_func(tinc_shk, rreturn):
                return (rreturn - self.R) * self.u.prime(
                    c_prime(
                        (self.R + (rreturn - self.R) * varsigma) * a / self.Gamma[-1]
                        + tinc_shk
                    )
                )

            GVtPsigma = (
                self.beta * a / self.Gamma[-1] * self.Distribution.E(Vshare_func)
            )
        else:
            GVtPsigma = np.inf
        return GVtPsigma


# -

# We create a discretized distribution of the risky asset return $\mathbf{R}_{t+1}$ with an expected excess return of 2 percent and a standard deviation of 15%. See more details regarding the log-normal distribution [here](https://www.econ2.jhu.edu/people/ccarroll/public/LectureNotes/MathFacts/MathFactsList.pdf).

# + code_folding=[0]
## set parameters for risky asset returns, i,e, make sure there is positive excessive return
## otherwise, the problem will be trivial
## discretized log-normal asset returns

theta_sigma_port = 0.15
theta_mu_port = -0.5 * theta_sigma_port**2
# Create "frozen" distribution instance
theta_z_port = stats.lognorm(s=theta_sigma_port, scale=exp(theta_mu_port))

RiskyR_grid_N = 7
RiskyR_sigma = 0.15  ## standard deviation of risky asset return
phi = 0.02  ## excess return from risky asset
RiskyR_mu = R + phi
# Create "frozen" distribution instance
mu = np.log(RiskyR_mu**2 / np.sqrt(RiskyR_sigma**2 + RiskyR_mu**2))

sigma = np.sqrt(np.log(RiskyR_sigma**2 / RiskyR_mu**2 + 1))

RiskyR_z = stats.lognorm(s=sigma, scale=np.exp(mu))

Distribution = DiscreteApproximationTwoIndependentDistribs(
    theta_grid_N,
    theta_z_port.cdf,
    theta_z_port.pdf,
    theta_z_port.ppf,
    RiskyR_grid_N,
    RiskyR_z.cdf,
    RiskyR_z.pdf,
    RiskyR_z.ppf,
)


# + code_folding=[0, 14, 64]
## Solve the portfolio choice problem in the second-to-the-last period

t_start = time()

#######################################################
## new parameterization for the portfolio problems
#######################################################

## higher risk aversion coefficient
rho_port = 6.0
u_port = Utility(gamma=rho_port)

### create a GothicMC instance
## notice we use a bigger coefficient of risk aversion
gothicMC = GothicMC(
    u_port, beta, rho_port, PermGroFac, R, Distribution=Distribution, share_grid_size=20
)

### set the a grid

a_max = 100.0
a_grid_size = 800
aVec_eee_big = setup_grids_expMult(a_min, a_max, a_grid_size)

#################################
### the last period
###############################

cVec_port = [0.0]
mVec_port = [0.0]
varsigmaVec_port = [0.0]

# print('period'+str(T))
for a in aVec_eee_big:
    varsigma = gothicMC.varsigma_Tminus1(a)  ## optimal share for a
    # print(varsigma)
    c = gothicMC.C_Tminus1(a)  ## optimal c given varsigma being optimal
    m = c + a
    c = np.minimum(c, m)
    cVec_port.append(c)
    mVec_port.append(m)
    varsigmaVec_port.append(varsigma)

# Set up the interpolation:
cFunc = InterpolatedUnivariateSpline(mVec_port, cVec_port, k=1)
varsigmaFunc = InterpolatedUnivariateSpline(mVec_port[1:], varsigmaVec_port[1:], k=1)

## save the grid in a dictionary
mGridPort_life = {T - 1: mVec_port}
cGridPort_life = {T - 1: cVec_port}
varsigmaGrid_life = {T - 1: varsigmaVec_port}

## save the interpolated function in a dictionary
cFuncPort_life = {T - 1: cFunc}
varsigma_life = {T - 1: varsigmaFunc}

#################################
### backward to earlier periods
###############################

for t in range(T - 2, 0, -1):
    # print('period'+str(t))
    cVec_port = [0.0]
    mVec_port = [0.0]
    varsigmaVec_port = [0.0]
    for a in aVec_eee_big:
        # print(a)
        varsigma = gothicMC.varsigma_t(a, cFunc)  ## optimal share for a
        # print(varsigma)
        c = gothicMC.C_t(a, cFunc)  ## optimal c given varsigma being optimal
        m = c + a
        c = np.minimum(c, m)
        cVec_port.append(c)
        mVec_port.append(m)
        varsigmaVec_port.append(varsigma)

    # Update the consumption function and share function
    cFunc = InterpolatedUnivariateSpline(mVec_port, cVec_port, k=1)
    varsigmaFunc = InterpolatedUnivariateSpline(
        mVec_port[1:], varsigmaVec_port[1:], k=1
    )

    ## save the policy grid in a dictionary
    mGridPort_life[t] = mVec_port
    cGridPort_life[t] = cVec_port
    varsigmaGrid_life[t] = varsigmaVec_port

    # save interpolated function:
    cFuncPort_life[t] = cFunc
    varsigma_life[t] = varsigmaFunc

t_finish = time()

print("Time taken, in seconds: " + str(t_finish - t_start))
# -


# Figure 20 plots the ﬁrst-period consumption function generated by the program; qualitatively it does not look much diﬀerent from the consumption functions generated by the program without portfolio choice.

# + code_folding=[]
############################
## Figure 20
############################
cFunc = cFuncPort_life[1]
plt.plot(mVec, cFunc(mVec), "k-")
plt.xlabel(r"$m$")
plt.ylabel(r"$c_{1}(m)$")
plt.title(r"$c_{1}(m)$ with Portfolio Choice")
# -


# Figure 21 plots $\varsigma_1(a_{1})$, the optimal portfolio share as a function of the end-of-period asset $a$ in the first period.
#
# - First, even with a coeﬃcient of relative risk aversion of 6, an equity premium of only 4 percent, and an annual standard deviation in equity returns of 15 percent, the optimal choice is for the agent to invest a proportion 1 (100 percent) of the portfolio in stocks (instead of the safe bank account with riskless return R  ) is at values of at  less than about 2.
#
# - Second, the proportion of the portfolio kept in stocks is declining in the level of wealth - i.e., the poor should hold all of their meager assets in stocks, while the rich should be cautious, holding more of their wealth in safe bank deposits and less in stocks. This seemingly bizarre (and highly counterfactual) prediction reﬂects the nature of the risks the consumer faces. Those consumers who are poor in measured ﬁnancial wealth are likely to derive a high proportion of future consumption from their labor income. Since by assumption labor income risk is uncorrelated with rate-of-return risk, the covariance between their future consumption and future stock returns is relatively low. By contrast, persons with relatively large wealth will be paying for a large proportion of future consumption out of that wealth, and hence if they invest too much of it in stocks their consumption will have a high covariance with stock returns. Consequently, they reduce that correlation by holding some of their wealth in the riskless form.

#####################################
## Figure 21
####################################
varsigmaGrid = varsigmaGrid_life[1][1:]
## drop the first point (share for zero asset corner solution)
plt.plot(aVec_eee_big, varsigmaGrid, "k-")
plt.xlabel(r"$a$")
plt.ylabel(r"$\varsigma_{1}(a)$")
plt.title(r"Portfolio Share in Risky Assets in the First Period $\varsigma(a)$")


# ### Cross-validation of the results
#
# In order to validate the method, we compare the MicroDSOP solution with that from HARK toolkit's PortfolioConsumer class. We configure the HARK class with exactly the same parameters used above.

# + code_folding=[]
# Solve the agent over a standard life-cycle

init_life_cycle_new = copy(init_lifecycle)
T_cyle = T - 1  ## minus 1 because T_cycle is nb periods in a life cycle - 1 in HARK
init_life_cycle_new["T_cycle"] = T_cyle
init_life_cycle_new["CRRA"] = rho_port
init_life_cycle_new["Rfree"] = R
init_life_cycle_new["LivPrb"] = [1.0] * T_cyle
init_life_cycle_new["PermGroFac"] = [1.0] * T_cyle
init_life_cycle_new["PermShkStd"] = [0.0] * T_cyle
init_life_cycle_new["PermShkCount"] = 1
init_life_cycle_new["TranShkStd"] = [theta_sigma_port] * T_cyle
init_life_cycle_new["UnempPrb"] = 0.0
init_life_cycle_new["RiskyAvg"] = [R + phi] * T_cyle  ## phi is risk premium
init_life_cycle_new["RiskyStd"] = [RiskyR_sigma] * T_cyle
init_life_cycle_new["RiskyCount"] = RiskyR_grid_N
init_life_cycle_new["RiskyAvgTrue"] = R + phi
init_life_cycle_new["RiskyStdTrue"] = RiskyR_sigma
init_life_cycle_new["DiscFac"] = beta
init_life_cycle_new["PermGroFacAgg"] = 1.0
# init_life_cycle_new['aXtraMin'] = a_min+0.00001
init_life_cycle_new["aXtraMax"] = a_max
init_life_cycle_new["aXtraCount"] = 800

LifeCycleType = PortfolioConsumerType(**init_life_cycle_new)

LifeCycleType.cycles = 1  ## life cycle problem instead of infinite horizon
LifeCycleType.vFuncBool = False  ## no need to calculate the value for the purpose here


# + code_folding=[0]
## solving the model
t0 = time()
LifeCycleType.solve()
LifeCycleType.cFunc = [
    LifeCycleType.solution[t].cFuncAdj for t in range(LifeCycleType.T_cycle)
]
LifeCycleType.ShareFunc = [
    LifeCycleType.solution[t].ShareFuncAdj for t in range(LifeCycleType.T_cycle)
]
t1 = time()
print(
    "Solving a "
    + str(LifeCycleType.T_cycle)
    + " period portfolio choice problem takes "
    + str(t1 - t0)
    + " seconds."
)


# + code_folding=[0]
## compare the consumption function for the T-1 period
which_period = 1
mGrid = mGridPort_life[which_period]
c_hark = LifeCycleType.cFunc[which_period - 1](mGrid)
c_dsop = cFuncPort_life[which_period](mGrid)

plt.plot(mGrid, c_hark, "r--", label="HARK")
plt.plot(mGrid, c_dsop, "k-", label="MicroDSOP")
plt.legend(loc=0)
plt.title("consumption function solved by MicroDSOP and HARK at $t=1$")
plt.xlabel("m")
plt.ylabel(r"$c_{1}(m)$")


# + code_folding=[0]
## Compare the solutions for portfolio at the first period in life cycle
which_period = 1


share_hark = LifeCycleType.ShareFunc[which_period - 1](mGrid)
share_dsop = varsigma_life[which_period](mGrid)

mGrid = mGrid
plt.plot(
    mGrid,
    share_hark,
    "r--",
    label="HARK solution",
)
plt.plot(mGrid, share_dsop, "k-", label="MicroDSOP solution")
plt.legend(loc=3)
plt.title("share function solved by MicroDSOP and HARK (at $t=1$)")
plt.xlabel(r"$m$")
plt.ylabel(r"$\varsigma_{1}(m)$")
plt.legend(loc=1)
# -


# As shown in the two figures above, the two methods produce visually identical values of optimal consumption and shares at $t=1$.

# ### Additional sanity checks
#
# We undertake a few additional sanity checks.
#
# First, let's check if the solutions are identical in the __second to the last__ period ($T-1$). In dynamic programming problems, it is always wise to start from the terminal solution. There are many good reasons for doing so. For instance,
#
# 1. solutions to earlier periods of life all depend on the terminal solution.
# 2. the terminal consumption function is trivial (consuming everything) and does not involve interpolation, we can focus on results unrelated to the use of interpolation tools.

# + code_folding=[0]
## Compare the solutions for portfolio at the first period in life cycle

which_period = T - 1
mGrid = mGrid
share_hark = LifeCycleType.ShareFunc[which_period - 1](mGrid)
share_dsop = varsigma_life[which_period](mGrid)
share_diff = share_hark - share_dsop

## plot
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 4))
ax1.plot(
    mGrid,
    share_hark,
    "r--",
    label="HARK solution",
)
ax1.plot(mGrid, share_dsop, "k-", label="MicroDSOP solution")
ax1.set_title("share function solved \n by MicroDSOP and HARK (at $T-1$)")
ax1.set_xlabel(r"$m$")
ax1.set_ylabel(r"$\varsigma_{T-1}(m)$")
ax1.legend(loc=0)
ax2.plot(mGrid, share_diff, "b--", label="Difference")
ax2.set_xlabel(r"$m$")
ax2.legend(loc=0)
ax2.set_title("Differences in solutions")
# -


# Second, let's use the exactly identical $a$_grid to solve the problem.

## this is the a grid used in HARK solution
a_grid = LifeCycleType.solution[0].aGrid


# + code_folding=[0, 20, 47]
## Solve the portfolio choice problem in the second-to-the-last (T-1) period

t_start = time()

#######################################################
## new parameterization for the portfolio problems
#######################################################

## new a grid
aVec_eee_big = a_grid[1:]

#################################
### the last period
###############################

cVec_port = [0.0]
mVec_port = [0.0]
varsigmaVec_port = [0.0]

# print('period'+str(T))
for a in aVec_eee_big:
    varsigma = gothicMC.varsigma_Tminus1(a)  ## optimal share for a
    # print(varsigma)
    c = gothicMC.C_Tminus1(a)  ## optimal c given varsigma being optimal
    m = c + a
    c = np.minimum(c, m)
    cVec_port.append(c)
    mVec_port.append(m)
    varsigmaVec_port.append(varsigma)

# Set up the interpolation:
cFunc = InterpolatedUnivariateSpline(mVec_port, cVec_port, k=1)
varsigmaFunc = InterpolatedUnivariateSpline(mVec_port[1:], varsigmaVec_port[1:], k=1)

## save the grid in a dictionary
mGridPort_life = {T - 1: mVec_port}
cGridPort_life = {T - 1: cVec_port}
varsigmaGrid_life = {T - 1: varsigmaVec_port}

## save the interpolated function in a dictionary
cFuncPort_life = {T - 1: cFunc}
varsigma_life = {T - 1: varsigmaFunc}

#################################
### backward to earlier periods
###############################

for t in range(T - 2, 0, -1):
    # print('period'+str(t))
    cVec_port = [0.0]
    mVec_port = [0.0]
    varsigmaVec_port = [0.0]
    for a in aVec_eee_big:
        # print(a)
        varsigma = gothicMC.varsigma_t(a, cFunc)  ## optimal share for a
        # print(varsigma)
        c = gothicMC.C_t(a, cFunc)  ## optimal c given varsigma being optimal
        m = c + a
        c = np.minimum(c, m)
        cVec_port.append(c)
        mVec_port.append(m)
        varsigmaVec_port.append(varsigma)

    # Update the consumption function and share function
    cFunc = InterpolatedUnivariateSpline(mVec_port, cVec_port, k=1)
    varsigmaFunc = InterpolatedUnivariateSpline(
        mVec_port[1:], varsigmaVec_port[1:], k=1
    )

    ## save the policy grid in a dictionary
    mGridPort_life[t] = mVec_port
    cGridPort_life[t] = cVec_port
    varsigmaGrid_life[t] = varsigmaVec_port

    # save interpolated function:
    cFuncPort_life[t] = cFunc
    varsigma_life[t] = varsigmaFunc

t_finish = time()

print("Time taken, in seconds: " + str(t_finish - t_start))


# + code_folding=[0]
## Compare the solutions

which_period = T - 1
mGrid = mGrid
share_hark_same_a = LifeCycleType.ShareFunc[which_period - 1](mGrid)
share_dsop_same_a = varsigma_life[which_period](mGrid)
share_diff_same_a = share_hark_same_a - share_dsop_same_a


## plot
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 4))
ax1.plot(
    mGrid,
    share_hark_same_a,
    "r--",
    label="HARK solution",
)
ax1.plot(mGrid, share_dsop_same_a, "k-", label="MicroDSOP solution")
ax1.legend(loc=0)
ax1.set_title("share function solved by MicroDSOP and HARK")
ax1.set_xlabel(r"$m$")
ax1.set_ylabel(r"$\varsigma_{T-1}(m)$")

ax2.plot(mGrid, share_diff_same_a, "b--", label="Difference")
ax2.set_xlabel(r"$m$")
ax2.legend(loc=0)
ax2.set_title("Differences in solutions")
# -


# We can see the two solutions give almost identical optimal share values.

# Third, let's directly compare the marginal values of a particular share is equal in the two procedures. We again focus on the second to the last period.
#
# - The marginal value of share $\varsigma$ is computed in SolvingMicroDSOPs with the function ''gothicMC.Vsigma_Tminus1($a$,$\varsigma$)''.
# - In the HARK.PortfolioConsumerType class, the marginal values at different grid of $a$ and share are saved as an attribute named _EndOfPrddvds_fxd[a_idx, share_idx]_.

# +
## prepare the same a and share grid

a_grid_size = len(a_grid)
share_grid = LifeCycleType.ShareGrid
share_grid_size = len(share_grid)


# +
## get the marginal values of share from HARK

HARK_mv = LifeCycleType.solution[which_period - 1].EndOfPrddvds_fxd[0:, :]
## which_period -2 is second the last period here


# +
## get the marginal values of for different $a$ and share from SolvingMicroDSOP

DSOP_mv = np.empty((a_grid_size, share_grid_size))

for i, a in enumerate(a_grid):
    for j, share in enumerate(share_grid):
        DSOP_mv[i, j] = gothicMC.Vsigma_Tminus1(a, share)


# + code_folding=[0]
## for a randomly choose a, plot the marginal value of share
a_grid_random = a_grid_size // 2


## plot
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 4))

ax1.set_title(r"$\mathfrak{v}^{\varsigma}(a,\varsigma)$ at a random $a$")
ax1.plot(share_grid, DSOP_mv[a_grid_random, :], label="SolvingMicroDSOP")
ax1.plot(share_grid, HARK_mv[a_grid_random, :], label="HARK")
ax1.hlines(0.0, xmin=0.0, xmax=1.0, linestyle="--", color="k", label="FOC")
ax1.set_xlabel(r"$\varsigma$")
ax1.set_ylabel(r"$\mathfrak{v}^{\varsigma}$")
ax1.legend(loc=0)

ax2.plot(
    share_grid,
    DSOP_mv[a_grid_random, :] - HARK_mv[a_grid_random, :],
    label="Difference",
)
ax2.set_title("Differences between \n solutions")
ax2.set_xlabel(r"$\varsigma$")
ax2.legend(loc=0)
# -


# The figure above plots the marginal values $\mathfrak{v}^{\varsigma}$ at different value of share $\varsigma$, at a random value of $a$, according to HARK and SolvingMicroDSPOs, respeceptively. The numerical differences are at an order of $10^{-9}$, which are almost infinitesimal.
