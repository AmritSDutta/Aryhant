import React from 'react';
import { Header } from './components/Header';
import { ChatPanel } from './components/ChatPanel';

export const App: React.FC = () => {
  return (
    <div className="app-container">
      <Header />
      <ChatPanel />
    </div>
  );
};

export default App;
