from typing import Dict, Callable, List, Any
from . import MarketAdapter
from ..MarketState import MarketState
from ..ProposedTrade import ProposedTrade
from poloniex import Poloniex
from time import sleep
from functools import partial
import operator

class LiveMarketAdapter (MarketAdapter):

    def __init__ (self,
                  market_history: MarketState,
                  config: Dict) -> None:
        self.polo = Poloniex(config['livetrading']['poloniex']['pk'],
                             config['livetrading']['poloniex']['sk'])
        self.MarketHistory = market_history
        self.balances = self.get_balances()
        self.fiat = config['fiat']


    def get_balances (self) -> Dict[str, float]:
        bals = self.polo.returnCompleteBalances()
        all_balances = {}
        for coin, bal, in bals.items():
            avail = float(bal['available'])
            if  avail > 0:
                all_balances[coin] = avail
        return all_balances


    def execute (self,
                 proposed_trades: List[ProposedTrade],
                 market_state: MarketState) -> None:
        for trade in proposed_trades:
            self._place_order(trade, market_state)
        self.balances = self.get_balances()


    '''
    Private methods
    '''


    def _adjust (self,
                 val: float,
                 operator: Callable,
                 tweak = 0.001) -> float:
        '''
        Pass in `operator.__add__`
        or `operator.__sub__`
        to move `val` up or down by `tweak`.
        '''
        return operator(val, (val*tweak))


    def _adjust_up (self,
                    val: float,
                    **kwargs) -> float:
        return self._adjust(val, operator.__add__, **kwargs)


    def _adjust_down (self,
                      val: float,
                      **kwargs) -> float:
        return self._adjust(val, operator.__sub__, **kwargs)

    # String, String, Float, Float, String -> Dict
    def _proposed_trade_measurement (self,
                                     direction: str,
                                     market: str,
                                     price: float,
                                     amount: float,
                                     order_status: str) -> Dict:
        return {
            'measurement': 'proposedTrade',
            'tags': {
                'order_status': order_status,
            },
            'fields': {
                'direction': direction,
                'market': market,
                'price': price,
                'amount': amount,
            }
        }


    def _purchase_helper (self,
                          direction: str,
                          market: str,
                          price: float,
                          amount: float,
                          purchase_fn: Callable,
                          adjust_fn: Callable) -> Dict:
        make_measurement = partial(self._proposed_trade_measurement,
                                   direction, market, price, amount)
        try:
            res = purchase_fn(
                market,
                price,
                amount,
                # Cancel order if not fulfilled in entirity at this price
                orderType = 'fillOrKill')
            measurement = make_measurement('filled')
            print(measurement)
        # If we can't fill the order at this price,
        except:
            measurement = make_measurement('killed')
            print(measurement)
            # recursively again at a (higher / lower) price
            adjusted_price = adjust_fn(price)
            return self._purchase_helper(
                direction,
                market,
                adjusted_price,
                amount,
                purchase_fn,
                adjust_fn
            )
        return res


    def _place_order (self,
                      proposed_trade: ProposedTrade,
                      market_state: MarketState) -> Dict:

        # if we're trading FROM fiat, that's a "sell"
        if proposed_trade.from_coin == market_state.fiat:
            return self._purchase_helper(
                'buy',
                proposed_trade.market_name,
                proposed_trade.market_price,
                proposed_trade.ask_amount,
                self.polo.buy,
                # We try to buy low,
                # But don't always get to,
                # so we adjust up if we must.
                self._adjust_up,
            )

        # if we're trading TO fiat, that's a "sell"
        elif proposed_trade.to_coin == market_state.fiat:
            return self._purchase_helper(
                'sell',
                proposed_trade.market_name,
                proposed_trade.market_price,
                proposed_trade.bid_amount,
                self.polo.sell,
                # We try to sell high,
                # But don't always get to,
                # so we adjust down if we must.
                self._adjust_down,
            )

        return {}
