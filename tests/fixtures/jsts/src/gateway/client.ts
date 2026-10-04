export async function send(
  id: string,
  amount: string | number,
  currency: string,
): Promise<{ id: string; status: 'paid' }> {
  return { id, status: 'paid' };
}
