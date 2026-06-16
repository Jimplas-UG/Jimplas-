/** Client-side broker routes (Binance Futures, webhooks, Telegram) — single entry for Metro. */
export { buildBrokerOrderIntent, postBrokerOrderWebhook } from './broker/webhookBroker';
export { canExecuteTrade } from './broker/tradeExecutionGates';
export { executeBrokerRoutes } from './broker/executeBrokerRoutes';
export { postTelegramSignalRelay, formatTelegramEligibleSignal } from './broker/telegramRelay';
