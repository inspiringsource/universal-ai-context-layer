import { send } from './gateway';
import type { Order } from '@models/order';
import { formatCents } from './format.js';
import Stripe from 'stripe';
import { missing } from './does-not-exist';

/*
 * function commentedOut(order) {}
 * class FakeInComment {}
 */
const notADeclaration = "export function fakeInString() {}";
const template = `class FakeInTemplate {}`;

export interface PaymentResult {
  id: string;
  status: 'paid' | 'failed';
}

export type Currency = 'USD' | 'EUR';

/** Charge an order through the gateway. */
export async function chargePayment(
  order: Order,
  currency: Currency = 'USD',
): Promise<PaymentResult> {
  const amount = formatCents(order.total);
  return send(order.id, amount, currency);
}

export const refundPayment = async (
  paymentId: string,
  reason?: string,
): Promise<void> => {
  await send(paymentId, 0, 'USD');
};

export class PaymentService {
  constructor(private readonly client: Stripe) {}

  process(order: Order): Promise<PaymentResult> {
    return chargePayment(order);
  }

  static fromEnv(): PaymentService {
    return new PaymentService(new Stripe());
  }
}

export class RefundService {
  process(paymentId: string): Promise<void> {
    function audit(id: string) {
      return id;
    }
    audit(paymentId);
    return refundPayment(paymentId);
  }
}

export function parseAmount(value: string): number;
export function parseAmount(value: number): number;
export function parseAmount(value: string | number): number {
  return Number(value);
}
