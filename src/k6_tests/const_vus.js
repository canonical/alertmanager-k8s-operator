import http from 'k6/http';
import { sleep } from 'k6';

export const options = {
  discardResponseBodies: true,
  scenarios: {
    contacts: {
      executor: 'constant-vus',
      vus: 10,
      duration: '10s',
    },
  },
};

export default function () {
  http.get('$url');
  // Injecting sleep
  // Total iteration time is sleep + time to finish request.
  sleep(0.5);
}

