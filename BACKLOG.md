how to feel Service Mesh is working

?? still no records at notifications and events table
reorganize Kafka topics and consumer groups
reorganize Redis key

??e-commerce, payment, AI model integration

?? adding scaling per RPS instead of CPU, rate limiting ? at Nginx, at each domain service
?? enforce RBAC using `X-Auth-*` headers for Downstream services (a JWT has 3 parts: header.payload.signature)

Rollback procedure
  kubectl rollout status deployment auth-service -n explore
                  history / undo / undo --to-revision=2
  helm history my-release
       rollback upgrade my-release 2                

REST asks:   Which endpoint?
Suppose your frontend dashboard needs: current user, latest orders, notifications
Frontend performs multiple requests GET /me GET /orders GET /notifications and aggregate JSON responses

multiple network round trips , over-fetching 
frontend orchestration complexity 
inconsistent payloads

GraphQL asks:  Which data fields?
POST /graphql
Query (instead of Request):
query DashboardQuery {
  me {    Id,     name,     roles   }
   orders {     Id,     status,     total   }

GraphQL can become dangerous if:
frontend queries too much nested data 
no query limits 
no caching strategy 
N+1 query problems 
So usually people add:
DataLoader 
persisted queries 
query depth limits 
caching layer 
GraphQL federation (later stage)

Please add GraphQL to the marketing-app and bff-marketing
So the BFF becomes dual-mode:
/api/*      -> REST
/graphql    -> GraphQL
Introducing gRPC / Protobuf gradually for migrated services while keeping REST/JSON for old services.