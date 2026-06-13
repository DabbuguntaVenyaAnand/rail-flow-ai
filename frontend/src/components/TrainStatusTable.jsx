import React from 'react';
import { useNetwork } from '../context/NetworkContext';

export default function TrainStatusTable() {
  const { trainStatus, fetchTrains } = useNetwork();

  const sorted = [...trainStatus]
    .sort((a, b) => b.delay_minutes - a.delay_minutes)
    .slice(0, 100);

  return (
    <div className="panel train-panel">
      <div className="panel-header-row">
        <h3 className="panel-title">Live Train Status</h3>
        <button className="btn btn-ghost btn-sm" onClick={fetchTrains}>Refresh</button>
      </div>
      <p className="panel-desc">GTFS-structured telemetry · auto-refreshes every 15s</p>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Train</th>
              <th>Name</th>
              <th>Station</th>
              <th>Delay</th>
              <th>Speed</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr><td colSpan={6} className="empty-row">No train data</td></tr>
            ) : (
              sorted.map(t => (
                <tr key={t.train_id} className={t.delay_minutes > 15 ? 'row-alert' : ''}>
                  <td><code>{t.train_id}</code></td>
                  <td>{t.train_name}</td>
                  <td><code>{t.current_station}</code></td>
                  <td>
                    <span className={`delay-badge ${t.delay_minutes > 15 ? 'delay-high' : t.delay_minutes > 0 ? 'delay-med' : 'delay-ok'}`}>
                      {t.delay_minutes} min
                    </span>
                  </td>
                  <td>{t.speed_kmh?.toFixed?.(0) ?? '—'} km/h</td>
                  <td className="text-muted">{formatTime(t.last_updated)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}
