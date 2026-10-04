import React from 'react';
import Button from './Button';

type ListProps<T> = {
  items: T[];
  render: (item: T) => string;
};

export function List<T>({ items, render }: ListProps<T>): JSX.Element {
  return (
    <ul>
      {items.map((item) => (
        <li key={render(item)}>
          <Button label={render(item)} onClick={() => undefined} />
        </li>
      ))}
    </ul>
  );
}
