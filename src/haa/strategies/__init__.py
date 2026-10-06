from .haa_4 import HAA4, HAA4Israel
from .haa_4_leveraged_2x import HAA4Leveraged2x
from .inflation_compass_steady import InflationCompassFast, InflationCompassFastIsrael, InflationCompassStandard, InflationCompassStandardIsrael, InflationCompassSteady, InflationCompassSteadyIsrael
from .haa_classic_no_qqq import HAAClassicNoQQQ
from .haa_classic_leveraged_no_qqq import HAAClassicLeveragedNoQQQ
from .haa_simple import HAASimple
from .haa_simple_leveraged_2x import HAASimpleLeveraged2x
from .haa_simple_israel import HAASimpleIsrael
from .buy_and_hold import BuyAndHoldACWI, BuyAndHoldGlobalIsrael, BuyAndHoldSPY, BuyAndHoldSPYIsrael, TA125SmartMomentum
from .century_momentum import CenturyMomentum, CenturyMomentumIsrael
from .growth_inflation import GrowthInflationConcentrated, GrowthInflationConcentratedIsrael, GrowthInflationDiversified
from .gem import GEM, GEMIsrael
from .ggcem import GGCEMLinkOriginal, GGCEMLinkOriginalIsrael
from .orthogonal_alpha import OrthogonalAlpha
from .baa import BAAG4Aggressive, BAAG4AggressiveIsrael
from .vaa import VAAG4
from .momentum_correlation_triplet import MomentumCorrelationTriplet

__all__ = ["BAAG4Aggressive", "BAAG4AggressiveIsrael", "BuyAndHoldACWI", "BuyAndHoldGlobalIsrael", "BuyAndHoldSPY", "BuyAndHoldSPYIsrael", "CenturyMomentum", "CenturyMomentumIsrael", "GEM", "GEMIsrael", "GGCEMLinkOriginal", "GGCEMLinkOriginalIsrael", "GrowthInflationConcentrated", "GrowthInflationConcentratedIsrael", "GrowthInflationDiversified", "HAA4", "HAA4Israel", "HAA4Leveraged2x", "HAAClassicNoQQQ", "HAAClassicLeveragedNoQQQ", "HAASimple", "HAASimpleLeveraged2x", "HAASimpleIsrael", "InflationCompassFast", "InflationCompassFastIsrael", "InflationCompassStandard", "InflationCompassStandardIsrael", "InflationCompassSteady", "InflationCompassSteadyIsrael", "MomentumCorrelationTriplet", "OrthogonalAlpha", "TA125SmartMomentum", "VAAG4"]
