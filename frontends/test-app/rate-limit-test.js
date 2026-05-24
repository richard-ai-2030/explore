import http from 'k6/http';
import { Counter } from 'k6/metrics';

const rateLimited = new Counter('rate_limited_requests');

export const options = {
  vus: 50,              // 50 concurrent users
  duration: '10s',
};

export default function () {
  const res = http.get('http://127.0.0.1:8888/api/auth/health');

  if (res.status === 429) {
    rateLimited.add(1);
  }

  console.log(`HTTP ${res.status}`);
}


/* configure       nginx.ingress.kubernetes.io/limit-rps: "10"
 * deploy Igress   kubectl apply -f k8s/cluster/infra-ingress-nginx.yaml
 * run test        k6 run frontends/test-app/rate-limit-test.js

 * many 200 OK
   some 429 Too Many Requests
 */