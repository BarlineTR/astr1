import WebSocket from 'ws';

async function testPanel() {
  // 1. Sign in to get session cookie
  const loginRes = await fetch('http://localhost:3000/api/auth/sign-in/email', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'origin': 'http://localhost:3000' },
    body: JSON.stringify({ email: 'admin@astro.com', password: 'Password123!' })
  });
  const cookie = loginRes.headers.get('set-cookie');
  console.log('Login cookie received:', !!cookie);

  // 2. Request panel ticket via POST /api/panel/jeton
  const ticketRes = await fetch('http://localhost:3000/api/panel/jeton', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'cookie': cookie
    },
    body: JSON.stringify({ cihazId: 'af2ffc9a-10c8-4ed2-875e-1ed10b0c1e99' })
  });
  const ticketData = await ticketRes.json();
  console.log('Ticket data:', ticketData);

  if (!ticketData.token) return;

  // 3. Connect to Gateway panel endpoint
  const ws = new WebSocket('ws://localhost:8420/ws/panel');
  ws.on('open', () => {
    console.log('Connected to gateway panel WS!');
    ws.send(JSON.stringify({
      kind: 'panel.merhaba',
      v: '1',
      token: ticketData.token
    }));
  });

  let sentCmd = false;

  ws.on('message', (data) => {
    const msg = JSON.parse(data.toString());
    console.log("-> Panel received:", msg.kind);
    if (msg.kind === 'gecit.panel-kabul') {
      console.log('Panel accepted! Can command:', msg.komutVerebilir);
    } else if (msg.kind === 'gecit.telemetri') {
      const yaw = msg.payload?.head?.actualYawDeg;
      console.log(`📡 [Telemetri] Kafa Açı: ${yaw}° | Yüzler: ${msg.payload?.faces?.length} | E-Stop: ${msg.payload?.safety?.eStop}`);
      
      if (!sentCmd) {
        sentCmd = true;
        console.log('🎯 Kafa hedef komutu gönderiliyor (+30°)...');
        ws.send(JSON.stringify({
          kind: 'panel.komut',
          komutId: 'test_cmd_1',
          komut: { kind: 'head.target', yawDeg: 30 }
        }));
      }

      if (yaw >= 28) {
        console.log(`🎉 BAŞARILI! Robot kafası hedef açıya (+30°) ulaştı! Anlık açı: ${yaw}°`);
        ws.close();
        process.exit(0);
      }
    }
  });

  ws.on('error', (err) => console.error('WS Error:', err));
}

testPanel().catch(console.error);
