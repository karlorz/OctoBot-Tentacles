#  Drakkar-Software OctoBot-Tentacles
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library.
import pytest
import pytest_asyncio
import os.path
import mock
import decimal

import async_channel.util as channel_util

import octobot_commons.asyncio_tools as asyncio_tools
import octobot_commons.enums as commons_enum
import octobot_commons.tests.test_config as test_config
import octobot_commons.constants as commons_constants

import octobot_backtesting.api as backtesting_api

import octobot_tentacles_manager.api as tentacles_manager_api

import octobot_trading.api as trading_api
import octobot_trading.exchange_channel as exchanges_channel
import octobot_trading.exchanges as exchanges
import octobot_trading.personal_data as trading_personal_data
import octobot_trading.enums as trading_enums
import octobot_trading.constants as trading_constants

import tentacles.Evaluator.TA as TA
import tentacles.Evaluator.Strategies as Strategies
import tentacles.Trading.Mode as Mode

import tests.test_utils.memory_check_util as memory_check_util
import tests.test_utils.config as test_utils_config
import tests.test_utils.test_exchanges as test_exchanges

import tentacles.Trading.Mode.dca_trading_mode.dca_trading as dca_trading

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def tools():
    trader = None
    try:
        tentacles_manager_api.reload_tentacle_info()
        mode, trader = await _get_tools()
        yield mode, trader
    finally:
        if trader:
            await _stop(trader.exchange_manager)


async def test_run_independent_backtestings_with_memory_check():
    """
    Should always be called first here to avoid other tests' related memory check issues
    """
    tentacles_setup_config = tentacles_manager_api.create_tentacles_setup_config_with_tentacles(
        Mode.DCATradingMode,
        Strategies.SimpleStrategyEvaluator,
        TA.RSIMomentumEvaluator,
        TA.EMAMomentumEvaluator
    )
    config = test_config.load_test_config()
    config[commons_constants.CONFIG_TIME_FRAME] = [commons_enum.TimeFrames.FOUR_HOURS]

    _CONFIG = {
        Mode.DCATradingMode.get_name(): {
            "buy_order_amount": "50q",
            "default_config": [
                "SimpleStrategyEvaluator"
            ],
            "entry_limit_orders_price_percent": 1,
            "exit_limit_orders_price_percent": 5,
            "minutes_before_next_buy": 10080,
            "required_strategies": [
                "SimpleStrategyEvaluator",
                "TechnicalAnalysisStrategyEvaluator"
            ],
            "secondary_entry_orders_amount": "12%",
            "secondary_entry_orders_count": 0,
            "secondary_entry_orders_price_percent": 5,
            "secondary_exit_orders_count": 2,
            "secondary_exit_orders_price_percent": 5,
            "stop_loss_price_percent": 10,
            "trigger_mode": "Maximum evaluators signals based",
            "use_market_entry_orders": False,
            "use_secondary_entry_orders": True,
            "use_secondary_exit_orders": True,
            "use_stop_losses": True,
            "use_take_profit_exit_orders": True
        },
        Strategies.SimpleStrategyEvaluator.get_name(): {
            "background_social_evaluators": [
                "RedditForumEvaluator"
            ],
            "default_config": [
                "DoubleMovingAverageTrendEvaluator",
                "RSIMomentumEvaluator"
            ],
            "re_evaluate_TA_when_social_or_realtime_notification": True,
            "required_candles_count": 1000,
            "required_evaluators": [
                "*"
            ],
            "required_time_frames": [
                "1h"
            ],
            "social_evaluators_notification_timeout": 3600
        },
        TA.RSIMomentumEvaluator.get_name(): {
            "long_threshold": 30,
            "period_length": 14,
            "short_threshold": 70,
            "trend_change_identifier": False
        },
        TA.EMAMomentumEvaluator.get_name(): {
            "period_length": 14,
            "price_threshold_percent": 2
        },
    }

    def config_proxy(tentacles_setup_config, klass):
        try:
            return _CONFIG[klass if isinstance(klass, str) else klass.get_name()]
        except KeyError:
            return {}

    with tentacles_manager_api.local_tentacle_config_proxy(config_proxy):
        await memory_check_util.run_independent_backtestings_with_memory_check(config, tentacles_setup_config)


def _get_config(tools, update):
    mode, trader = tools
    config = tentacles_manager_api.get_tentacle_config(trader.exchange_manager.tentacles_setup_config, mode.__class__)
    return {**config, **update}


async def test_init_default_values(tools):
    mode, producer, consumer, trader = await _init_mode(tools, _get_config(tools, {}))
    assert mode.use_market_entry_orders is True
    assert mode.trigger_mode is dca_trading.TriggerMode.TIME_BASED
    assert mode.minutes_before_next_buy == 10080

    assert mode.entry_limit_orders_price_multiplier == decimal.Decimal("0.05")
    assert mode.use_secondary_entry_orders is False
    assert mode.secondary_entry_orders_count == 0
    assert mode.secondary_entry_orders_amount == ""
    assert mode.secondary_entry_orders_price_multiplier == decimal.Decimal("0.05")

    assert mode.use_take_profit_exit_orders is False
    assert mode.exit_limit_orders_price_multiplier == decimal.Decimal("0.05")
    assert mode.use_secondary_exit_orders is False
    assert mode.secondary_exit_orders_count == 0
    assert mode.secondary_exit_orders_price_multiplier == decimal.Decimal("0.05")

    assert mode.use_stop_loss is False
    assert mode.stop_loss_price_multiplier == decimal.Decimal("0.1")


async def test_init_config_values(tools):
    update = {
        "buy_order_amount": "50q",
        "entry_limit_orders_price_percent": 3,
        "exit_limit_orders_price_percent": 1,
        "minutes_before_next_buy": 333,
        "secondary_entry_orders_amount": "12%",
        "secondary_entry_orders_count": 0,
        "secondary_entry_orders_price_percent": 5,
        "secondary_exit_orders_count": 333,
        "secondary_exit_orders_price_percent": 2,
        "stop_loss_price_percent": 10,
        "trigger_mode": "Maximum evaluators signals based",
        "use_market_entry_orders": False,
        "use_secondary_entry_orders": True,
        "use_secondary_exit_orders": True,
        "use_stop_losses": True,
        "use_take_profit_exit_orders": True
    }
    mode, producer, consumer, trader = await _init_mode(tools, _get_config(tools, update))
    assert mode.use_market_entry_orders is False
    assert mode.trigger_mode is dca_trading.TriggerMode.MAXIMUM_EVALUATORS_SIGNALS_BASED
    assert mode.minutes_before_next_buy == 333

    assert mode.entry_limit_orders_price_multiplier == decimal.Decimal("0.03")
    assert mode.use_secondary_entry_orders is True
    assert mode.secondary_entry_orders_count == 0
    assert mode.secondary_entry_orders_amount == "12%"
    assert mode.secondary_entry_orders_price_multiplier == decimal.Decimal("0.05")

    assert mode.use_take_profit_exit_orders is True
    assert mode.exit_limit_orders_price_multiplier == decimal.Decimal("0.01")
    assert mode.use_secondary_exit_orders is True
    assert mode.secondary_exit_orders_count == 333
    assert mode.secondary_exit_orders_price_multiplier == decimal.Decimal("0.02")

    assert mode.use_stop_loss is True
    assert mode.stop_loss_price_multiplier == decimal.Decimal("0.1")


async def test_trigger_dca(tools):
    update = {}
    mode, producer, consumer, trader = await _init_mode(tools, _get_config(tools, update))
    with mock.patch.object(producer, "_process_entries", mock.AsyncMock()) as _process_entries_mock, \
         mock.patch.object(producer, "_process_exits", mock.AsyncMock()) as _process_exits_mock:
        await producer.trigger_dca("crypto", "symbol", trading_enums.EvaluatorStates.NEUTRAL)
        assert producer.state is trading_enums.EvaluatorStates.NEUTRAL
        # neutral is not triggering anything
        _process_entries_mock.assert_not_called()
        _process_exits_mock.assert_not_called()

        await producer.trigger_dca("crypto", "symbol", trading_enums.EvaluatorStates.LONG)
        assert producer.state is trading_enums.EvaluatorStates.LONG
        _process_entries_mock.assert_called_once_with("crypto", "symbol", trading_enums.EvaluatorStates.LONG)
        _process_exits_mock.assert_called_once_with("crypto", "symbol", trading_enums.EvaluatorStates.LONG)
        _process_entries_mock.reset_mock()
        _process_exits_mock.reset_mock()

        await producer.trigger_dca("crypto", "symbol", trading_enums.EvaluatorStates.VERY_SHORT)
        assert producer.state is trading_enums.EvaluatorStates.VERY_SHORT
        _process_entries_mock.assert_called_once_with("crypto", "symbol", trading_enums.EvaluatorStates.VERY_SHORT)
        _process_exits_mock.assert_called_once_with("crypto", "symbol", trading_enums.EvaluatorStates.VERY_SHORT)


async def test_process_entries(tools):
    update = {}
    mode, producer, consumer, trader = await _init_mode(tools, _get_config(tools, update))
    with mock.patch.object(producer, "submit_trading_evaluation", mock.AsyncMock()) as submit_trading_evaluation_mock, \
         mock.patch.object(producer, "cancel_symbol_open_orders", mock.AsyncMock()) as cancel_symbol_open_orders_mock, \
         mock.patch.object(producer, "_send_alert_notification", mock.AsyncMock()) as _send_alert_notification_mock:

        await producer._process_entries("crypto", "symbol", trading_enums.EvaluatorStates.NEUTRAL)
        # neutral state: does not create orders
        submit_trading_evaluation_mock.assert_not_called()
        cancel_symbol_open_orders_mock.assert_not_called()
        _send_alert_notification_mock.assert_not_called()

        await producer._process_entries("crypto", "symbol", trading_enums.EvaluatorStates.SHORT)
        await producer._process_entries("crypto", "symbol", trading_enums.EvaluatorStates.VERY_SHORT)
        # short state: not yet supported
        submit_trading_evaluation_mock.assert_not_called()
        _send_alert_notification_mock.assert_not_called()

        for state in (trading_enums.EvaluatorStates.LONG, trading_enums.EvaluatorStates.VERY_LONG):
            await producer._process_entries("crypto", "symbol", state)
            # short state: not yet supported
            submit_trading_evaluation_mock.assert_called_once_with(
                cryptocurrency="crypto",
                symbol="symbol",
                time_frame=None,
                final_note=None,
                state=state
            )
            _send_alert_notification_mock.assert_called_once_with("symbol", state, "entry")
            _send_alert_notification_mock.reset_mock()
            submit_trading_evaluation_mock.reset_mock()


async def test_get_channels_registration(tools):
    update = {}
    mode, producer, consumer, trader = await _init_mode(tools, _get_config(tools, update))
    mode.trigger_mode = dca_trading.TriggerMode.TIME_BASED
    assert producer.get_channels_registration() == []
    mode.trigger_mode = dca_trading.TriggerMode.MAXIMUM_EVALUATORS_SIGNALS_BASED
    assert producer.get_channels_registration() == [
        producer.TOPIC_TO_CHANNEL_NAME[commons_enum.ActivationTopics.EVALUATION_CYCLE.value]
    ]


async def _process_exits(tools):
    # not implemented
    update = {}
    mode, producer, consumer, trader = await _init_mode(tools, _get_config(tools, update))
    with mock.patch.object(producer, "submit_trading_evaluation", mock.AsyncMock()) as submit_trading_evaluation_mock:
        for state in trading_enums.EvaluatorStates:
            await producer._process_exits("crypto", "symbol", state)
        submit_trading_evaluation_mock.assert_not_called()


async def test_split_entry_quantity(tools):
    update = {}
    mode, producer, consumer, trader = await _init_mode(tools, _get_config(tools, update))
    symbol = mode.symbol
    symbol_market = trader.exchange_manager.exchange.get_market_status(symbol, with_fixer=False)
    assert consumer._split_entry_quantity(
        decimal.Decimal("123"), 1, decimal.Decimal("12"), decimal.Decimal("15"), symbol_market
    ) == [(1, decimal.Decimal("123"))]
    assert consumer._split_entry_quantity(
        decimal.Decimal("123"), 2, decimal.Decimal("12"), decimal.Decimal("15"), symbol_market
    ) == [(1, decimal.Decimal("61.5")), (2, decimal.Decimal("61.5"))]
    assert consumer._split_entry_quantity(
        decimal.Decimal("123"), 3, decimal.Decimal("12"), decimal.Decimal("15"), symbol_market
    ) == [(1, decimal.Decimal("41")), (2, decimal.Decimal("41")), (3, decimal.Decimal("41"))]
    # not enough for 3 orders, do 1
    assert consumer._split_entry_quantity(
        decimal.Decimal("0.0001"), 3, decimal.Decimal("12"), decimal.Decimal("15"), symbol_market
    ) == [(1, decimal.Decimal('0.0001'))]
    # not enough for 3 orders, do 0
    assert consumer._split_entry_quantity(
        decimal.Decimal("0.000001"), 3, decimal.Decimal("12"), decimal.Decimal("15"), symbol_market
    ) == []


async def test_create_entry_with_chained_exit_orders(tools):
    update = {}
    mode, producer, consumer, trader = await _init_mode(tools, _get_config(tools, update))
    mode.stop_loss_price_multiplier = decimal.Decimal("0.12")
    mode.exit_limit_orders_price_multiplier = decimal.Decimal("0.07")
    mode.secondary_exit_orders_price_multiplier = decimal.Decimal("0.035")
    mode.secondary_exit_orders_count = 0
    symbol = mode.symbol
    symbol_market = trader.exchange_manager.exchange.get_market_status(symbol, with_fixer=False)
    entry_price = decimal.Decimal("1222")
    entry_order = trading_personal_data.create_order_instance(
        trader=trader,
        order_type=trading_enums.TraderOrderType.BUY_LIMIT,
        symbol=symbol,
        current_price=entry_price,
        quantity=decimal.Decimal("3"),
        price=entry_price
    )
    with mock.patch.object(mode, "create_order", mock.AsyncMock(side_effect=lambda *args, **kwargs: args[0])) \
         as create_order_mock:
        # no chained stop loss
        # no take profit
        mode.use_stop_loss = False
        mode.use_take_profit_exit_orders = False
        await consumer._create_entry_with_chained_exit_orders(entry_order, entry_price, symbol_market)
        create_order_mock.assert_called_once_with(entry_order, params=None)
        assert entry_order.chained_orders == []
        # reset values
        create_order_mock.reset_mock()
        entry_order.chained_orders = []

        # chained stop loss
        # no take profit
        mode.use_stop_loss = True
        mode.use_take_profit_exit_orders = False
        await consumer._create_entry_with_chained_exit_orders(entry_order, entry_price, symbol_market)
        create_order_mock.assert_called_once_with(entry_order, params=None)
        assert len(entry_order.chained_orders) == 1
        stop_loss = entry_order.chained_orders[0]
        assert isinstance(stop_loss, trading_personal_data.StopLossOrder)
        assert isinstance(stop_loss.state, trading_personal_data.PendingCreationChainedOrderState)
        assert stop_loss.symbol == entry_order.symbol
        assert stop_loss.origin_quantity == entry_order.origin_quantity
        assert stop_loss.origin_price == entry_price * (1 - mode.stop_loss_price_multiplier)
        assert stop_loss.triggered_by is entry_order
        assert stop_loss.order_group is None
        # reset values
        create_order_mock.reset_mock()
        entry_order.chained_orders = []

        # no chained stop loss
        # take profit
        mode.use_stop_loss = False
        mode.use_take_profit_exit_orders = True
        await consumer._create_entry_with_chained_exit_orders(entry_order, entry_price, symbol_market)
        create_order_mock.assert_called_once_with(entry_order, params=None)
        create_order_mock.reset_mock()
        assert len(entry_order.chained_orders) == 1
        take_profit = entry_order.chained_orders[0]
        assert isinstance(take_profit, trading_personal_data.SellLimitOrder)
        assert isinstance(take_profit.state, trading_personal_data.PendingCreationChainedOrderState)
        assert take_profit.symbol == entry_order.symbol
        assert take_profit.origin_quantity == entry_order.origin_quantity
        assert take_profit.origin_price == entry_price * (1 + mode.exit_limit_orders_price_multiplier)
        assert take_profit.triggered_by is entry_order
        assert take_profit.order_group is None
        # reset values
        create_order_mock.reset_mock()
        entry_order.chained_orders = []

        # chained stop loss
        # take profit
        mode.use_stop_loss = True
        mode.use_take_profit_exit_orders = True
        await consumer._create_entry_with_chained_exit_orders(entry_order, entry_price, symbol_market)
        create_order_mock.assert_called_once_with(entry_order, params=None)
        create_order_mock.reset_mock()
        assert len(entry_order.chained_orders) == 2
        stop_loss = entry_order.chained_orders[0]
        take_profit = entry_order.chained_orders[1]
        assert isinstance(stop_loss, trading_personal_data.StopLossOrder)
        assert isinstance(stop_loss.state, trading_personal_data.PendingCreationChainedOrderState)
        assert isinstance(take_profit, trading_personal_data.SellLimitOrder)
        assert isinstance(take_profit.state, trading_personal_data.PendingCreationChainedOrderState)
        assert take_profit.order_group is stop_loss.order_group
        assert isinstance(take_profit.order_group, trading_personal_data.OneCancelsTheOtherOrderGroup)
        # reset values
        create_order_mock.reset_mock()
        entry_order.chained_orders = []

        # chained stop loss
        # 3 take profit (initial + 2 additional)
        mode.use_stop_loss = True
        mode.use_take_profit_exit_orders = True
        mode.use_secondary_exit_orders = True
        mode.secondary_exit_orders_count = 2
        await consumer._create_entry_with_chained_exit_orders(entry_order, entry_price, symbol_market)
        create_order_mock.assert_called_once_with(entry_order, params=None)
        create_order_mock.reset_mock()
        assert len(entry_order.chained_orders) == 2 * 3  # 3 stop loss & take profits couples
        stop_losses = [
            order
            for order in entry_order.chained_orders
            if isinstance(order, trading_personal_data.StopLossOrder)
        ]
        take_profits = [
            order
            for order in entry_order.chained_orders
            if isinstance(order, trading_personal_data.SellLimitOrder)
        ]
        # ensure only stop losses and take profits in chained orders
        assert len(entry_order.chained_orders) == len(stop_losses) + len(take_profits)
        total_stop_quantity = trading_constants.ZERO
        total_tp_quantity = trading_constants.ZERO
        previous_stop_price = entry_price
        previous_tp_price = trading_constants.ZERO
        for (stop_loss, take_profit) in zip(stop_losses, take_profits):
            assert isinstance(stop_loss.state, trading_personal_data.PendingCreationChainedOrderState)
            assert isinstance(take_profit.state, trading_personal_data.PendingCreationChainedOrderState)
            total_tp_quantity += take_profit.origin_quantity
            total_stop_quantity += stop_loss.origin_quantity
            # constant price with stop losses
            if not previous_tp_price:
                previous_stop_price = stop_loss.origin_price
            else:
                assert stop_loss.origin_price == previous_stop_price
            # increasing price with take profits
            assert take_profit.origin_price > previous_tp_price
            previous_tp_price = take_profit.origin_price
            # ensure orders are grouped together
            assert take_profit.order_group is stop_loss.order_group
            assert isinstance(take_profit.order_group, trading_personal_data.OneCancelsTheOtherOrderGroup)
        # ensure selling the total entry quantity
        assert total_stop_quantity == entry_order.origin_quantity
        assert total_tp_quantity == entry_order.origin_quantity
        # reset values
        create_order_mock.reset_mock()
        entry_order.chained_orders = []

        # chained stop loss
        # 3 take profit (initial + 2 additional)
        mode.use_stop_loss = True
        mode.use_take_profit_exit_orders = True
        # disable use_secondary_exit_orders
        mode.use_secondary_exit_orders = False
        mode.secondary_exit_orders_count = 2    # disabled
        await consumer._create_entry_with_chained_exit_orders(entry_order, entry_price, symbol_market)
        create_order_mock.assert_called_once_with(entry_order, params=None)
        create_order_mock.reset_mock()
        assert len(entry_order.chained_orders) == 2  # 1 take profit and one stop loss: no secondary exit is allowed
        stop_losses = [
            order
            for order in entry_order.chained_orders
            if isinstance(order, trading_personal_data.StopLossOrder)
        ]
        take_profits = [
            order
            for order in entry_order.chained_orders
            if isinstance(order, trading_personal_data.SellLimitOrder)
        ]
        # ensure only stop losses and take profits in chained orders
        assert len(stop_losses) == 1
        assert len(take_profits) == 1
        assert stop_losses[0].origin_quantity == take_profits[0].origin_quantity == entry_order.origin_quantity


async def test_create_entry_order(tools):
    update = {}
    mode, producer, consumer, trader = await _init_mode(tools, _get_config(tools, update))
    symbol = mode.symbol
    symbol_market = trader.exchange_manager.exchange.get_market_status(symbol, with_fixer=False)
    price = decimal.Decimal("1222")
    order_type = trading_enums.TraderOrderType.BUY_LIMIT
    quantity = decimal.Decimal("42")
    current_price = decimal.Decimal("22222")
    with mock.patch.object(
        consumer, "_create_entry_with_chained_exit_orders", mock.AsyncMock(return_value=None)
    ) as _create_entry_with_chained_exit_orders_mock:
        created_orders = []
        assert await consumer._create_entry_order(
            order_type, quantity, price, symbol_market, symbol, created_orders, current_price
        ) is False
        _create_entry_with_chained_exit_orders_mock.assert_called_once()
        assert created_orders == []
    with mock.patch.object(
        consumer, "_create_entry_with_chained_exit_orders", mock.AsyncMock(return_value="created_order")
    ) as _create_entry_with_chained_exit_orders_mock:
        created_orders = []
        assert await consumer._create_entry_order(
            order_type, quantity, price, symbol_market, symbol, created_orders, current_price
        ) is True
        _create_entry_with_chained_exit_orders_mock.assert_called_once()
        created_order = _create_entry_with_chained_exit_orders_mock.mock_calls[0].args[0]
        assert created_order.order_type == order_type
        assert created_order.origin_quantity == quantity
        assert created_order.origin_price == price
        assert created_order.symbol == symbol
        assert created_order.created_last_price == current_price
        assert created_orders == ["created_order"]


async def test_create_new_orders(tools):
    update = {}
    mode, producer, consumer, trader = await _init_mode(tools, _get_config(tools, update))
    mode.secondary_entry_orders_count = 0
    symbol = mode.symbol

    def _create_basic_order(side):
        created_order = trading_personal_data.Order(trader)
        created_order.symbol = symbol
        created_order.side = side
        created_order.origin_quantity = decimal.Decimal("0.1")
        created_order.origin_price = decimal.Decimal("1000")
        return created_order

    async def _create_entry_order(_, __, ___, ____, _____, created_orders, ______):
        created_order = _create_basic_order(trading_enums.TradeOrderSide.BUY)
        created_orders.append(created_order)
        return created_order

    with mock.patch.object(
        consumer, "_create_entry_order", mock.AsyncMock(side_effect=_create_entry_order)
    ) as _create_entry_order_mock, mock.patch.object(
        mode, "cancel_order", mock.AsyncMock()
    ) as cancel_order_mock:
        # neutral state
        assert await consumer.create_new_orders(symbol, None, trading_enums.EvaluatorStates.NEUTRAL.value) == []
        cancel_order_mock.assert_not_called()
        _create_entry_order_mock.assert_not_called()
        # no configured amount
        mode.trading_config[trading_constants.CONFIG_BUY_ORDER_AMOUNT] = ""
        assert await consumer.create_new_orders(symbol, None, trading_enums.EvaluatorStates.LONG.value) == []
        cancel_order_mock.assert_not_called()
        _create_entry_order_mock.assert_not_called()
        # no configured secondary amount
        mode.trading_config[trading_constants.CONFIG_BUY_ORDER_AMOUNT] = "12%"
        mode.secondary_entry_orders_amount = ""
        await consumer.create_new_orders(symbol, None, trading_enums.EvaluatorStates.LONG.value)
        cancel_order_mock.assert_not_called()
        _create_entry_order_mock.assert_called_once()
        _create_entry_order_mock.reset_mock()

        # with secondary orders but no configured secondary amount
        mode.secondary_entry_orders_count = 4
        await consumer.create_new_orders(symbol, None, trading_enums.EvaluatorStates.LONG.value)
        cancel_order_mock.assert_not_called()
        # only called once: missing secondary quantity prevents secondary orders creation
        _create_entry_order_mock.assert_called_once()
        _create_entry_order_mock.reset_mock()

        mode.use_market_entry_orders = False
        mode.use_secondary_entry_orders = True
        mode.secondary_entry_orders_amount = "20q"
        await consumer.create_new_orders(symbol, None, trading_enums.EvaluatorStates.LONG.value)
        cancel_order_mock.assert_not_called()
        # called as many times as there are orders to create
        assert _create_entry_order_mock.call_count == 1 + 4
        # ensure each secondary order has a lower price
        previous_price = None
        for i, call in enumerate(_create_entry_order_mock.mock_calls):
            if i == 0:
                assert call.args[1] == decimal.Decimal('0.24')    # initial quantity
            else:
                assert call.args[1] == decimal.Decimal('0.02')    # secondary quantity
            assert call.args[0] is trading_enums.TraderOrderType.BUY_LIMIT
            call_price = call.args[2]
            if previous_price is None:
                previous_price = call_price
            else:
                assert call_price < previous_price
        _create_entry_order_mock.reset_mock()

        mode.use_market_entry_orders = True
        await consumer.create_new_orders(symbol, None, trading_enums.EvaluatorStates.VERY_LONG.value)
        cancel_order_mock.assert_not_called()
        # called as many times as there are orders to create
        assert _create_entry_order_mock.call_count == 1 + 4
        for i, call in enumerate(_create_entry_order_mock.mock_calls):
            expected_type = trading_enums.TraderOrderType.BUY_MARKET \
                if i == 0 else trading_enums.TraderOrderType.BUY_LIMIT
            assert call.args[0] is expected_type
        _create_entry_order_mock.reset_mock()

        # with existing orders: cancel them
        existing_orders = [
            _create_basic_order(trading_enums.TradeOrderSide.BUY),
            _create_basic_order(trading_enums.TradeOrderSide.BUY),
            _create_basic_order(trading_enums.TradeOrderSide.SELL),
        ]
        for order in existing_orders:
            await trader.exchange_manager.exchange_personal_data.orders_manager.upsert_order_instance(order)

        assert trader.exchange_manager.exchange_personal_data.orders_manager.get_all_orders(symbol=symbol) == \
               existing_orders
        await consumer.create_new_orders(symbol, None, trading_enums.EvaluatorStates.LONG.value)
        assert cancel_order_mock.call_count == 2
        assert cancel_order_mock.mock_calls[0].args[0] == existing_orders[0]
        assert cancel_order_mock.mock_calls[1].args[0] == existing_orders[1]
        cancel_order_mock.reset_mock()
        # called as many times as there are orders to create
        assert _create_entry_order_mock.call_count == 1 + 4
        _create_entry_order_mock.reset_mock()

        # without enough funds to create every secondary order
        mode.secondary_entry_orders_count = 30  # can't create 30 orders, each using 100 USD of available funds
        await consumer.create_new_orders(symbol, None, trading_enums.EvaluatorStates.LONG.value)
        assert cancel_order_mock.call_count == 2   # still cancel open orders
        assert cancel_order_mock.mock_calls[0].args[0] == existing_orders[0]
        assert cancel_order_mock.mock_calls[1].args[0] == existing_orders[1]
        portfolio = trading_api.get_portfolio(trader.exchange_manager)
        order_example = _create_basic_order(trading_enums.TradeOrderSide.BUY)
        # ensure used all funds
        assert portfolio["USDT"].available / _create_entry_order_mock.call_count == \
               order_example.origin_quantity * order_example.origin_price
        cancel_order_mock.reset_mock()
        # called as many times as there are orders to create
        # 10 orders out of 30 got skipped
        assert _create_entry_order_mock.call_count == 1 + 19
        _create_entry_order_mock.reset_mock()


async def _check_open_orders_count(trader, count):
    assert len(trading_api.get_open_orders(trader.exchange_manager)) == count


async def _get_tools(symbol="BTC/USDT"):
    config = test_config.load_test_config()
    config[commons_constants.CONFIG_SIMULATOR][commons_constants.CONFIG_STARTING_PORTFOLIO]["USDT"] = 2000
    exchange_manager = test_exchanges.get_test_exchange_manager(config, "binance")
    exchange_manager.tentacles_setup_config = test_utils_config.get_tentacles_setup_config()

    # use backtesting not to spam exchanges apis
    exchange_manager.is_simulated = True
    exchange_manager.is_backtesting = True
    backtesting = await backtesting_api.initialize_backtesting(
        config,
        exchange_ids=[exchange_manager.id],
        matrix_id=None,
        data_files=[os.path.join(test_config.TEST_CONFIG_FOLDER,
                                 "AbstractExchangeHistoryCollector_1586017993.616272.data")])
    exchange_manager.exchange = exchanges.ExchangeSimulator(
        exchange_manager.config, exchange_manager, backtesting
    )
    await exchange_manager.exchange.initialize()
    for exchange_channel_class_type in [exchanges_channel.ExchangeChannel, exchanges_channel.TimeFrameExchangeChannel]:
        await channel_util.create_all_subclasses_channel(exchange_channel_class_type, exchanges_channel.set_chan,
                                                         exchange_manager=exchange_manager)

    trader = exchanges.TraderSimulator(config, exchange_manager)
    await trader.initialize()

    mode = Mode.DCATradingMode(config, exchange_manager)
    mode.symbol = None if mode.get_is_symbol_wildcard() else symbol
    # trading mode is not initialized: to be initialized with the required config in tests

    # add mode to exchange manager so that it can be stopped and freed from memory
    exchange_manager.trading_modes.append(mode)

    # set BTC/USDT price at 1000 USDT
    trading_api.force_set_mark_price(exchange_manager, symbol, 1000)

    return mode, trader


async def _init_mode(tools, config):
    mode, trader = tools
    await mode.initialize(trading_config=config)
    return mode, mode.producers[0], mode.get_trading_mode_consumers()[0], trader


async def _fill_order(order, trader, trigger_update_callback=True, ignore_open_orders=False, consumer=None,
                      closed_orders_count=1):
    initial_len = len(trading_api.get_open_orders(trader.exchange_manager))
    await order.on_fill(force_fill=True)
    if order.status == trading_enums.OrderStatus.FILLED:
        if not ignore_open_orders:
            assert len(trading_api.get_open_orders(trader.exchange_manager)) == initial_len - closed_orders_count
        if trigger_update_callback:
            await asyncio_tools.wait_asyncio_next_cycle()
        else:
            with mock.patch.object(consumer, "create_new_orders", new=mock.AsyncMock()):
                await asyncio_tools.wait_asyncio_next_cycle()


async def _stop(exchange_manager):
    for importer in backtesting_api.get_importers(exchange_manager.exchange.backtesting):
        await backtesting_api.stop_importer(importer)
    await exchange_manager.exchange.backtesting.stop()
    await exchange_manager.stop()