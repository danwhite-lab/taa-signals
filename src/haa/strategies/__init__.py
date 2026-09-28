from .haa_4 import HAA4
from .haa_4_leveraged_2x import HAA4Leveraged2x
from .inflation_compass_steady import InflationCompassFast, InflationCompassFastIsrael, InflationCompassStandard, InflationCompassStandardIsrael, InflationCompassSteady, InflationCompassSteadyIsrael
from .haa_classic_no_qqq import HAAClassicNoQQQ
from .haa_classic_leveraged_no_qqq import HAAClassicLeveragedNoQQQ
from .haa_simple import HAASimple
from .haa_simple_leveraged_2x import HAASimpleLeveraged2x
from .haa_simple_israel import HAASimpleIsrael
from .buy_and_hold import TA125SmartMomentum
from .century_momentum import CenturyMomentum, CenturyMomentumIsrael
from .growth_inflation import GrowthInflationConcentrated, GrowthInflationConcentratedIsrael, GrowthInflationDiversified
from .orthogonal_alpha import OrthogonalAlpha
from .vaa import VAAG4

__all__ = ["CenturyMomentum", "CenturyMomentumIsrael", "GrowthInflationConcentrated", "GrowthInflationConcentratedIsrael", "GrowthInflationDiversified", "HAA4", "HAA4Leveraged2x", "HAAClassicNoQQQ", "HAAClassicLeveragedNoQQQ", "HAASimple", "HAASimpleLeveraged2x", "HAASimpleIsrael", "InflationCompassFast", "InflationCompassFastIsrael", "InflationCompassStandard", "InflationCompassStandardIsrael", "InflationCompassSteady", "InflationCompassSteadyIsrael", "OrthogonalAlpha", "TA125SmartMomentum", "VAAG4"]
