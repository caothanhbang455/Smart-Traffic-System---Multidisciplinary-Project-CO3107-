// src/App.tsx
import { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

interface TrafficData {
  [key: string]: {
    vehicles: number;
    light: 'red' | 'yellow' | 'green';
    last_update: string;
  };
}

function App() {
  const [traffic, setTraffic] = useState<TrafficData>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Hàm lấy dữ liệu từ backend
  const fetchTraffic = async () => {
    try {
      const res = await axios.get('http://127.0.0.1:5000/api/traffic');
      setTraffic(res.data);
      setError(null);
    } catch (err) {
      setError('Can not connect to backend. Check if backend is running!');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // Gọi API lần đầu + polling mỗi 4 giây
  useEffect(() => {
    fetchTraffic(); // lần đầu
    const interval = setInterval(fetchTraffic, 4000);
    return () => clearInterval(interval); // cleanup
  }, []);

  // Hàm gửi lệnh đổi đèn
  const changeLight = async (intersection: string, newLight: 'red' | 'green' | 'yellow') => {
    try {
      const res = await axios.post('http://127.0.0.1:5000/api/control', {
        intersection,
        light: newLight,
      });
      alert(res.data.message || 'Đã gửi lệnh!');
      fetchTraffic(); // refresh ngay
    } catch (err) {
      alert('Lỗi khi gửi lệnh');
      console.error(err);
    }
  };

  if (loading) return <div className="loading">Loading traffic conditions...</div>;

  return (
    <div className="app">
      <h1>🚦 Smart Traffic Light System</h1>

      {error && <p className="error">{error}</p>}

      <div className="intersections">
        {Object.entries(traffic).map(([inter, data]) => (
          <div key={inter} className="card">
            <h2>{inter.replace('_', ' ').toUpperCase()}</h2>
            <p>Số xe hiện tại: <strong>{data.vehicles}</strong></p>
            <p>Cập nhật lúc: {data.last_update || '—'}</p>

            <div className="light-status">
              <div className={`light ${data.light}`}>
                {data.light.toUpperCase()}
              </div>
            </div>

            <div className="controls">
              <button onClick={() => changeLight(inter, 'green')} className="btn green">
                Xanh
              </button>
              <button onClick={() => changeLight(inter, 'yellow')} className="btn yellow">
                Vàng
              </button>
              <button onClick={() => changeLight(inter, 'red')} className="btn red">
                Đỏ
              </button>
            </div>
          </div>
        ))}
      </div>

      <p className="note">Data is automatically updated every 4 seconds</p>
    </div>
  );
}

export default App;