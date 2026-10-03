import { useCallback, useEffect, useRef, useState } from 'react';

const MAX_ATTEMPTS = 2;
const ICE_TIMEOUT_MS = 2000;

function waitForIce(peer) {
  if (peer.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const finish = () => {
      peer.removeEventListener('icegatheringstatechange', check);
      clearTimeout(timer);
      resolve();
    };
    const check = () => {
      if (peer.iceGatheringState === 'complete') finish();
    };
    const timer = setTimeout(finish, ICE_TIMEOUT_MS);
    peer.addEventListener('icegatheringstatechange', check);
  });
}

/**
 * Pulls the MediaMTX WebRTC stream straight into a <video> element via WHEP.
 *
 * state is one of: idle | connecting | playing | fallback | failed
 * `fallback` means WHEP did not come up and the caller should embed the
 * MediaMTX player page instead.
 */
export function useWhep(whepUrl, { enabled = true } = {}) {
  const videoRef = useRef(null);
  const peerRef = useRef(null);
  const attemptsRef = useRef(0);
  const retryRef = useRef(null);
  const aliveRef = useRef(true);
  const [state, setState] = useState('idle');
  const [error, setError] = useState(null);

  const teardown = useCallback(() => {
    if (retryRef.current) {
      clearTimeout(retryRef.current);
      retryRef.current = null;
    }
    const peer = peerRef.current;
    if (peer) {
      peer.onconnectionstatechange = null;
      peer.ontrack = null;
      peer.close();
      peerRef.current = null;
    }
  }, []);

  const connect = useCallback(async () => {
    if (!whepUrl || !aliveRef.current) return;

    teardown();
    attemptsRef.current += 1;
    setState('connecting');
    setError(null);

    const peer = new RTCPeerConnection({ iceServers: [] });
    peerRef.current = peer;
    peer.addTransceiver('video', { direction: 'recvonly' });

    const stream = new MediaStream();
    peer.ontrack = (event) => {
      stream.addTrack(event.track);
      if (videoRef.current) videoRef.current.srcObject = stream;
    };

    const fail = (reason) => {
      if (!aliveRef.current || peerRef.current !== peer) return;
      teardown();
      setError(reason);
      if (attemptsRef.current < MAX_ATTEMPTS) {
        setState('connecting');
        retryRef.current = setTimeout(connect, 1500);
      } else {
        setState('fallback');
      }
    };

    peer.onconnectionstatechange = () => {
      if (peerRef.current !== peer) return;
      if (peer.connectionState === 'connected') {
        attemptsRef.current = 0;
        setState('playing');
      } else if (peer.connectionState === 'failed' || peer.connectionState === 'closed') {
        fail(`connection ${peer.connectionState}`);
      }
    };

    try {
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      await waitForIce(peer);
      if (peerRef.current !== peer) return;

      const response = await fetch(whepUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: peer.localDescription.sdp,
      });
      if (!response.ok) throw new Error(`WHEP responded ${response.status}`);

      const answer = await response.text();
      if (peerRef.current !== peer) return;
      await peer.setRemoteDescription({ type: 'answer', sdp: answer });
    } catch (err) {
      fail(err.message);
    }
  }, [whepUrl, teardown]);

  const reconnect = useCallback(() => {
    attemptsRef.current = 0;
    connect();
  }, [connect]);

  useEffect(() => {
    aliveRef.current = true;
    if (enabled && whepUrl) connect();
    return () => {
      aliveRef.current = false;
      teardown();
    };
  }, [enabled, whepUrl, connect, teardown]);

  return { videoRef, state, error, reconnect };
}
