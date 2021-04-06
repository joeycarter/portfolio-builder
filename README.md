# Portfolio Builder

A simple tool to build an ETF-based portfolio with a mix of bonds and equities depending on your preferred risk level and available cash.

The ETF selection used here is based on the [Model ETF Portfolios](https://www.canadianportfoliomanagerblog.com/model-etf-portfolios/) article from the [Canadian Portfolio Manager](https://www.canadianportfoliomanagerblog.com/).

## Usage

### Build a Portfolio from Scratch

Run `portfolio-builder.py` and input your desired risk level, available cash to invest, and preferred ETF provider.
The "risk level" is an integer on a scale from 0 (all bonds) to 10 (all equities).

For example, to build a balanced (50% bonds, 50% equities) portfolio with $1000 CAD using Vanguard ETFs:

```console
$ ./portfolio-builder.py -r 5 -c 10000 -e vanguard
Retrieving current ETF prices...
[*********************100%***********************]  7 of 7 completed
Done

Your portfolio:
~~~~~~~~~~~~~~~

ETF       Price          To    Value         % of    Target % of
          (CAD)    Buy/Sell    (CAD)    Portfolio      Portfolio
------  -------  ----------  -------  -----------  -------------
VAB.TO   25.850         113  2921.05        29.76          29.45
VBU.TO   25.680          33   847.44         8.63           8.54
VBG.TO   27.455          43  1180.56        12.03          12.01
VCN.TO   38.530          38  1464.14        14.92          15.00
VUN.TO   72.360          28  2026.08        20.64          20.67
VIU.TO   31.760          32  1016.32        10.35          10.37
VEE.TO   39.940           9   359.46         3.66           3.96

Total cost:    $9815.06 CAD
Leftover cash: $184.94 CAD
```

### Rebalance an existing portfolio

If you have an existing account, input the number of shares you own per ETF as a `.csv` file in the `accounts/` directory. For example:

```console
$ cat accounts/example.csv
VAB.TO,VBU.TO,VBG.TO,VCN.TO,VUN.TO,VIU.TO,VEE.TO
100,20,30,42,20,60,10
```

Then, to rebalance your portfolio according to the 50% bonds, 50% equities targets as above, run:

```console
$ ./portfolio-builder.py -r 5 -c 0 -e vanguard --rebalance
Reading current account data...
Retrieving current ETF prices...
[*********************100%***********************]  7 of 7 completed
Done

Your portfolio:
~~~~~~~~~~~~~~~

ETF       Price     Current          To       Total    Value         % of    Target % of
          (CAD)    Quantity    Buy/Sell    Quantity    (CAD)    Portfolio      Portfolio
------  -------  ----------  ----------  ----------  -------  -----------  -------------
VAB.TO   25.850         100           5         105  2714.25        29.62          29.45
VBU.TO   25.680          20          10          30   770.40         8.41           8.54
VBG.TO   27.455          30          10          40  1098.20        11.98          12.01
VCN.TO   38.530          42          -6          36  1387.08        15.14          15.00
VUN.TO   72.360          20           6          26  1881.36        20.53          20.67
VIU.TO   31.760          60         -30          30   952.80        10.40          10.37
VEE.TO   39.940          10          -1           9   359.46         3.92           3.96

Total cost:    $-129.16 CAD
Leftover cash: $129.16 CAD
```

You can also rebalance while investing additional cash, e.g. with $2000 CAD:

```console
$ ./portfolio-builder.py -r 5 -c 2000 -e vanguard --rebalance
Reading current account data...
Retrieving current ETF prices...
[*********************100%***********************]  7 of 7 completed
Done

Your portfolio:
~~~~~~~~~~~~~~~

ETF       Price     Current          To       Total    Value         % of    Target % of
          (CAD)    Quantity    Buy/Sell    Quantity    (CAD)    Portfolio      Portfolio
------  -------  ----------  ----------  ----------  -------  -----------  -------------
VAB.TO   25.850         100          28         128  3308.80        29.65          29.45
VBU.TO   25.680          20          17          37   950.16         8.51           8.54
VBG.TO   27.455          30          19          49  1345.29        12.06          12.01
VCN.TO   38.530          42           1          43  1656.79        14.85          15.00
VUN.TO   72.360          20          12          32  2315.52        20.75          20.67
VIU.TO   31.760          60         -24          36  1143.36        10.25          10.37
VEE.TO   39.940          10           1          11   439.34         3.94           3.96

Total cost:    $1866.56 CAD
Leftover cash: $133.44 CAD
```
