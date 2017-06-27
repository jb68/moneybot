from .. import Purchase
import numpy as np
import pandas as pd

'''
Generic utils
'''

def filter_none (lst):
    return [x for x in lst if x != None]

def coin_names (market_name):
    coins = market_name.split('_')
    return coins[0], coins[1]

def available_markets (chart_data, fiat):
    return set([ k for k in chart_data.keys() if k.startswith(fiat) ])

def held_coins_with_chart_data (chart_data, balances,
                                fiat='BTC'):
    avail_markets = available_markets(chart_data, fiat)
    # Extract the coin name from each available fiat-to-coin market
    avail_coins   = [coin_names(market)[1] for market in avail_markets]
    # The fiat is always available, so we'll add that to the list as well
    avail_coins  += [fiat]
    return set(balances.held_coins()).intersection(avail_coins)

def get_purchase (current_chart_data, from_coin, from_amount, to_coin,
                  fee=0.0025, fiat='BTC', price_key='weightedAverage',
                  min_fiat_value_for_trade=0.0001):
    '''
    Returns a Purchase, or None.
    '''
    def purchase_amount (investment, price):
        '''
        Get the amount of some coin purchased,
        given an investment (in quote), and a price (in quote),
        accounting for trading fees.
        '''
        in_amt = investment - (investment * fee)
        return in_amt / price
    # if the coin is fiat,
    if to_coin == fiat:
        market_name = '{!s}_{!s}'.format(fiat, from_coin)
        to_price = 1 / current_chart_data[market_name][price_key]
        to_amount = purchase_amount(from_amount, to_price)
        if to_amount > min_fiat_value_for_trade:
            return Purchase(from_coin, from_amount, to_coin, to_amount)
    # if coin is not fiat,
    # and we're buying more than 0.0001 BTC worth,
    elif to_coin != fiat and from_amount > min_fiat_value_for_trade:
        market_name = '{!s}_{!s}'.format(fiat, to_coin)
        to_price = current_chart_data[market_name][price_key]
        to_amount = purchase_amount(from_amount, to_price)
        return Purchase(from_coin, from_amount, to_coin, to_amount)
    # If none of these conditions are met,
    # we return None.
    # None values are explicitly filtered at the ends of the system,
    # e.g. in balances.apply_purchases() or market.make_purchase()
    return None


'''
Initial allocation tools
'''

def initial_purchases_equal_alloc (chart_data, balances, fiat):
    avail = available_markets(chart_data, fiat)
    amount_to_invest_per_coin = balances[fiat] / ( len(avail) + 1.0 )
    purchases = [ get_purchase(chart_data,
                                fiat,
                                amount_to_invest_per_coin,
                                coin_names(market)[1])
                for market in avail ]
    return purchases


'''
Rebalancing tools
'''


def rebalancing_purchases_equal_alloc (coins_to_rebalance, chart_data, balances, fiat):
    avail = available_markets(chart_data, fiat)
    total_value = balances.estimate_total_fiat_value(chart_data)
    ideal_value_fiat = total_value / len(avail) # TODO maybe +1? like above?
    purchases_to_fiat = []
    for coin in coins_to_rebalance:
        if coin != fiat:
            purchases_to_fiat.append(
                get_purchase(
                    chart_data,
                    coin,
                    balances[coin] - ideal_value_fiat,
                    fiat
                ))
    purchases_to_fiat = filter_none(purchases_to_fiat)

    est_bals_after_fiat_trades = balances.apply_purchases(None, purchases_to_fiat)

    if fiat in coins_to_rebalance and len(purchases_to_fiat) > 0:
        fiat_after_trades        = est_bals_after_fiat_trades[fiat]
        to_redistribute          = fiat_after_trades - ideal_value_fiat
        markets_divested_from    = [fiat + '_' + purchase.from_coin
                                    for purchase in purchases_to_fiat]
        markets_to_buy           = set(avail) - set(markets_divested_from)
        to_redistribute_per_coin = to_redistribute / len(markets_to_buy)
        purchase_from_fiat       = [get_purchase(chart_data,
                                                 fiat,
                                                 to_redistribute_per_coin,
                                                 coin_names(market)[1])
                                    for market in avail ]
        return purchases_to_fiat + purchase_from_fiat

    return purchases_to_fiat


'''
is_buffed tools
'''

def median (est_values):
    return np.median(list(est_values.values()))

def sum_of (est_values):
    return sum(list(est_values.values()))

def is_buffed (coin, coin_values,
               multiplier=2.0,
               ):
    median_value  = median(coin_values)
    if coin_values[coin] > (median_value * multiplier):
        return True
    return False

def is_buffed_by_power (coin, coin_values,
                        power_of = 1.2):
    median_value  = median(coin_values)
    if median_value > 1:
        median_to_power = pow(median_value, power_of)
    else:
        median_to_power = pow(median_value, 1/power_of)
    val = coin_values[coin]
    if val > median_to_power:
        return True
    return False


'''
is_crashing tools
'''
# PandasSeries -> (PandasSeries, PandasSeries)
def emas (price_series, shortw=96, longw=2400, **kwargs):
    long_ema  = price_series.ewm(com=longw).mean()
    short_ema = price_series.ewm(com=shortw).mean()
    return long_ema, short_ema

def percentage_price_oscillator (price_series, **kwargs):
    longe, shorte = emas(price_series, **kwargs)
    ppo           = (shorte - longe) / longe
    return ppo

# PandasSeries -> PandasSeries
def ppo_histogram (price_series, **kwargs):
    ppo           = percentage_price_oscillator(price_series)
    ppo_ema       = ppo.ewm(com=9).mean()
    ppo_hist      = pd.DataFrame(ppo - ppo_ema)
    return ppo_hist

def latest_ppo_hist (price_series):
    ppo_hist = ppo_histogram(price_series)
    latest   = ppo_hist.iloc[-1].values[0]
    return latest
