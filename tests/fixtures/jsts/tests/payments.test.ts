import { chargePayment } from '../src/payments';

test('charges', async () => {
  await chargePayment({ id: 'o1', total: 100 });
});
