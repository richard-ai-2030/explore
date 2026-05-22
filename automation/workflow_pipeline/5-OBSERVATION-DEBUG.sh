#-------------- OBSERVE KUBERNETES --------------
kubectl exec -it auth-service-84b7cd99b4-x924k -n explore -- env | grep REDIS
kubectl exec -it auth-service-75799cb866-25wlz -n explore -- /bin/bash
  apt update && apt install curl iputils-ping -y

kubectl logs -f deployment/leads-acquisition-service -n explore
kubectl logs -n explore $(kubectl get pods -n explore | grep auth-service | awk '{print $1}' | head -n 1)

  kubectl describe deployment auth-service -n explore
  kubectl describe svc auth-service -n explore
  kubectl describe pod auth-service-65bc895d5b-8d5wf -n explore
  kubectl get pod auth-service-65bc895d5b-8d5wf  -n explore -o jsonpath='{.spec.containers[*].name}'
  #kubectl delete deployment auth-service -n explore
  #kubectl delete svc auth-service -n explore
  #kubectl set env deployment --all -n explore POSTGRES_HOST=172.19.0.5 KAFKA_BOOTSTRAP_SERVERS=172.19.0.7
  #kubectl set env deployment/auth-service -n explore REDIS_URL=redis://172.19.0.6:6379/0  
  #kubectl delete hpa --all -n explore
  #kubectl scale deployment --all --replicas=1 -n explore


#-------------- OBSERVE REDIS --------------
docker exec -it redis redis-cli MONITOR                         # execute command in an existing Docker container
  docker logs -f redis        #docker logs --tail 20 redis

kubectl run redis --rm -it --image=redis:7-alpine -- sh         # create a Debug pod in Kubernetes
  redis-cli -h 172.19.0.6 MONITOR
  redis-cli -h 172.19.0.6 -p 6379
    SET test:key "hello"         GET test:key        DEL test:key


#-------------- OBSERVE KAFKA --------------
# create a Docker container then execute observing Kafka Consumer
docker run -it --rm --network explore_infra_net confluentinc/cp-kafka:latest bash
  kafka-console-consumer --bootstrap-server kafka:29092 --topic explore.events

# execute Producing in an existing Docker container
docker exec -it kafka     kafka-console-producer --bootstrap-server kafka:29092 --topic explore.events
  docker logs -f kafka        docker logs --tail 20 kafka


kubectl run kafka --rm -it --restart=Never --image=confluentinc/cp-kafka:latest bash
  kafka-console-consumer --bootstrap-server 172.19.0.7:9092 --topic explore.events

#-------------- OBSERVE CLICKHOUSE --------------
curl -s "http://172.19.0.8:8123/?query=SELECT%20count()%20FROM%20explore.events"
curl -s "http://172.19.0.8:8123/?query=SELECT%20domain,event_type,count()%20FROM%20explore.events%20GROUP%20BY%20domain,event_type%20ORDER%20BY%20count()%20DESC%20LIMIT%2010"

kubectl run kafkaproducer --rm -it --restart=Never --image=confluentinc/cp-kafka:latest --command --   \
  kafka-console-producer --bootstrap-server 172.19.0.7:9092 --topic explore.events


#-------------- OBSERVE POSTGRES --------------
kubectl run postgres   --rm -it   --restart=Never   --image=postgres:16-alpine   --env="PGPASSWORD=postgres"   --command --   \
psql -h 172.19.0.5 -U postgres -d notification_service \
-c "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 1"

kubectl run postgres   --rm -it   --restart=Never   --image=postgres:16-alpine   --env="PGPASSWORD=postgres"   --command --   \
psql -h 172.19.0.5 -U postgres -d auth_service \
-c "SELECT * FROM outbox_events ORDER BY created_at DESC LIMIT 1"
-c "\dt"
  
  docker exec -it postgres psql -U postgres
  #psql -h localhost -p 5432 -U postgres