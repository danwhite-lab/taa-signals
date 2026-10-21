"""Compare parity: only monthly returns allow absolute roundoff <=1e-12."""
from dataclasses import fields, is_dataclass
import pandas as pd
import pytest
from test_compare import install, saved, MONTHLY, RVOL
from server import compare as page
from server import compare_presentation as view
from haa.portfolio_comparison import compare_portfolios as original_compare


def assert_exact(left,right,path="root"):
    if isinstance(left,pd.DataFrame):
        # Only Compare monthly return columns may differ by roundoff. All
        # other engine fields remain bit-exact; displayed numbers stay exact.
        returns = [c for c in left if str(c).endswith("monthly_return")]
        if path.endswith(".monthly") and returns:
            pd.testing.assert_frame_equal(left.drop(columns=returns),right.drop(columns=returns),check_exact=True,obj=path)
            pd.testing.assert_frame_equal(left[returns],right[returns],check_exact=False,atol=1e-12,rtol=0,obj=path)
            pd.testing.assert_frame_equal(left[returns].map(lambda x: f"{x:.2%}"),right[returns].map(lambda x: f"{x:.2%}"),check_exact=True,obj=path)
        else:
            pd.testing.assert_frame_equal(left,right,check_exact=True,obj=path)
    elif isinstance(left,pd.Series):
        pd.testing.assert_series_equal(left,right,check_exact=True,obj=path)
    elif isinstance(left,pd.Index):
        pd.testing.assert_index_equal(left,right,exact=True,obj=path)
    elif is_dataclass(left):
        for item in fields(left):assert_exact(getattr(left,item.name),getattr(right,item.name),path+"."+item.name)
    elif isinstance(left,dict):
        assert list(left)==list(right),path
        for key in left:assert_exact(left[key],right[key],path+"."+str(key))
    else:assert left==right,path


@pytest.mark.parametrize("method,labels",[("monthly",MONTHLY),("daily",["Century Momentum","HAA-Simple",RVOL]),("daily",["Century Momentum","Inflation Compass Standard",RVOL])])
def test_every_engine_frame_is_bit_exact(monkeypatch,method,labels):
    install(monkeypatch,labels)
    records=[saved("FAKE-A",labels[:2],[60,40]),saved("FAKE-B",labels,[40,30,30])]
    request=page.Inputs(mode="portfolios",portfolio_ids=["FAKE-A","FAKE-B"],method=method,initial=10000,fee_pct=.05,tax_enabled=True)
    chosen=page.selection(request,records);loaded=page.load(request,chosen)
    args=(loaded["inputs"],request.initial,request.fee_pct/100,request.tax_enabled,request.tax_rate/100)
    discovery=original_compare(*args,drift=method=="daily")
    before=original_compare(*args,discovery.common_index[0],discovery.common_index[-1],drift=method=="daily")
    after,_=page.calculate(request,loaded)
    assert_exact(before,after)
    # All table values shown at two decimals must agree, not just NAVs.
    left=view.present(request,before,loaded,(before.common_index[0].date(),before.common_index[-1].date()))["public"]["tables"]
    right=view.present(request,after,loaded,(after.common_index[0].date(),after.common_index[-1].date()))["public"]["tables"]
    for key in left:
        if "display_rows" in left[key]: assert left[key]["display_rows"]==right[key]["display_rows"]


def test_tolerance_is_absolute_monthly_returns_only():
    left=pd.DataFrame({"pre_tax_monthly_return":[.12345],"pre_tax_value":[100.]})
    right=left.copy();right.loc[0,"pre_tax_monthly_return"]+=1e-14
    assert_exact(left,right,"x.monthly")
    with pytest.raises(AssertionError): assert_exact(left,right,"x.daily")
    right.loc[0,"pre_tax_value"]+=1e-14
    with pytest.raises(AssertionError): assert_exact(left,right,"x.monthly")
    right=left.copy();right.loc[0,"pre_tax_monthly_return"]+=1e-10
    with pytest.raises(AssertionError): assert_exact(left,right,"x.monthly")
