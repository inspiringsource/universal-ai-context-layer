import React from 'react';

export default function Button({ label, onClick }) {
  const handleClick = (event) => {
    event.preventDefault();
    onClick(label);
  };
  return <button onClick={handleClick}>{label}</button>;
}
