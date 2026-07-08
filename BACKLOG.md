?? still no records at notifications and events table
reorganize Kafka topics and consumer groups
reorganize Redis key

?? enforce RBAC using `X-Auth-*` headers for Downstream services (a JWT has 3 parts: header.payload.signature)

?? gRPC / Protobuf gradually while keeping REST/JSON for older services

BFF-SERVICE:  GraphQL  POST /graphql  
  query DashboardQuery {
    me {    Id,     name,     roles   }
    orders {     Id,     status,     total   }

  GraphQL can become dangerous if:
    frontend queries too much nested data 
    N+1 query problems 

  So usually people add:
    DataLoader 
    persisted queries 
    query depth limits 
    caching layer 
    GraphQL federation