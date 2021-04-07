# Portfolio Builder

![GitHub](https://img.shields.io/github/license/joeycarter/portfolio-builder)

A simple tool to build an ETF-based portfolio with a mix of bonds and equities depending on your preferred risk level and available cash.

The ETF selection used here is based on the [Model ETF Portfolios](https://www.canadianportfoliomanagerblog.com/model-etf-portfolios/) article from the [Canadian Portfolio Manager](https://www.canadianportfoliomanagerblog.com/).

## Usage

### Build a portfolio from scratch

Run `portfolio-builder.py` and input your desired risk level, available cash to invest, and preferred ETF provider.
The "risk level" is an integer on a scale from 0 (all bonds) to 10 (all equities).

For example, to build a balanced (50% bonds, 50% equities) portfolio with $10000 CAD using Vanguard ETFs:

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

You can also rebalance while investing additional cash.
For example, to rebalance your portfolio according to the 50% bonds, 50% equities targets as above, while investing an additional $2000 CAD, run:

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

### Allow fractional shares

You'll notice there is large amount of cash left over in the above examples.
This is due to the requirement that the number of shares to buy or sell is an integer number and that the total cost is less than the cash available to invest.
If you want to allow fractions when computing the number of shares to buy/sell, use the `--fractions` option, for example:

```console
$ ./portfolio-builder.py -r 5 -c 10000 -e vanguard --fractions
Retrieving current ETF prices...
[*********************100%***********************]  7 of 7 completed
Done

Your portfolio:
~~~~~~~~~~~~~~~

ETF       Price          To    Value         % of    Target % of
          (CAD)    Buy/Sell    (CAD)    Portfolio      Portfolio
------  -------  ----------  -------  -----------  -------------
VAB.TO   25.850      113.93  2945.00        29.45          29.45
VBU.TO   25.680       33.26   854.00         8.54           8.54
VBG.TO   27.455       43.74  1201.00        12.01          12.01
VCN.TO   38.530       38.93  1500.00        15.00          15.00
VUN.TO   72.360       28.57  2067.00        20.67          20.67
VIU.TO   31.760       32.65  1037.00        10.37          10.37
VEE.TO   39.940        9.91   396.00         3.96           3.96

Total cost:    $10000.00 CAD
Leftover cash: $0.00 CAD
```

### How "current" are the "current prices"?

The portfolio builder retrieves the current stock prices using the [*yfinance*](https://pypi.org/project/yfinance/) package, and uses the most recent "Close" price of that stock.
Therefore the prices listed by the portfolio builder are not guaranteed to be the current "live" market price of the stock, and should serve as an approximate value only.

## Disclaimer

**THIS SOFTWARE IS NOT INVESTMENT ADVICE**

This software is for informational purposes only. You should not construe any such information or other material as legal, tax, investment, financial, or other advice. Nothing contained in this software constitutes a solicitation, recommendation, endorsement, to buy or sell any securities or other financial instruments in this or in any other jurisdiction in which such solicitation or offer would be unlawful under the securities laws of such jurisdiction.

The content on this software is information of a general nature and does not address the circumstances of any particular individual or entity. Nothing in this software constitutes professional and/or financial advice, nor does any information in this software constitute a comprehensive or complete statement of the matters discussed or the law relating thereto. You alone assume the sole responsibility of evaluating the merits and risks associated with the use of any information or other content in this software before making any decisions based on such information or other content. In exchange for using this software, you agree not to hold me, the copyright holder of this software, my affiliates or any third party service provider liable for any possible claim for damages arising from any decision you make based on information or other content made available to you through this software.

**INVESTMENT RISKS**

There are risks associated with investing in securities. Investing in stocks, bonds, exchange traded funds, mutual funds, and money market funds involve risk of loss. Loss of principal is possible. Some high-risk investments may use leverage, which will accentuate gains & losses. Foreign investing involves special risks, including a greater volatility and political, economic and currency risks and differences in accounting methods. A security's or a firm's past investment performance is not a guarantee or predictor of future investment performance.

**DO YOUR OWN RESEARCH**

This software is intended to be used and must be used for information and education purposes only. It is very important to do your own analysis before making any investment based on your own personal circumstances. You should take independent financial advice from a professional in connection with, or independently research and verify, any information that you find in this software and wish to rely upon, whether for the purpose of making an investment decision or otherwise.
