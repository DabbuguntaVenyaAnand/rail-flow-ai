import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { NetworkProvider } from './context/NetworkContext';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Pathfinder from './pages/Pathfinder';
import Operations from './pages/Operations';
import Analytics from './pages/Analytics';
import './styles/app.css';

export default function App() {
  return (
    <NetworkProvider>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/pathfinder" element={<Pathfinder />} />
            <Route path="/ops" element={<Operations />} />
            <Route path="/analytics" element={<Analytics />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </NetworkProvider>
  );
}
