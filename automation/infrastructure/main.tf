locals {
  services = {
    postgres = {
      image = "postgres:16-alpine"
      env = ["POSTGRES_DB=app", "POSTGRES_USER=postgres", "POSTGRES_PASSWORD=postgres"]
      ports = [{ internal = 5432, external = 5432 }]
      volumes = [{ container_path = "/var/lib/postgresql/data", name = docker_volume.postgres_data.name }]
    }
    /*mongodb = {
      image = "mongo:7"
      env = []
      ports = [{ internal = 27017, external = 27017 }]
      volumes = [{ container_path = "/data/db", name = docker_volume.mongodb_data.name }]
    }
    elasticsearch = {
      image = "docker.elastic.co/elasticsearch/elasticsearch:8.15.1"
      env = ["discovery.type=single-node", "xpack.security.enabled=false", "ES_JAVA_OPTS=-Xms512m -Xmx512m"]
      ports = [{ internal = 9200, external = 9200 }]
      volumes = []
    }*/
    redis = {
      image = "redis:7-alpine"
      env = []
      ports = [{ internal = 6379, external = 6379 }]
      volumes = []
    }
    zookeeper = {
      image = "confluentinc/cp-zookeeper:7.6.1"
      env = ["ZOOKEEPER_CLIENT_PORT=2181", "ZOOKEEPER_TICK_TIME=2000"]
      ports = [{ internal = 2181, external = 2181 }]
      volumes = []
    }
    kafka = {
      image = "confluentinc/cp-kafka:7.6.1"
      env = [
        "KAFKA_BROKER_ID=1",
        "KAFKA_ZOOKEEPER_CONNECT=zookeeper:2181",
        "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT",
        "KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:29092,PLAINTEXT_HOST://172.19.0.7:9092",
        "KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:29092,PLAINTEXT_HOST://0.0.0.0:9092",
        "KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT",
        "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1",
        "KAFKA_AUTO_CREATE_TOPICS_ENABLE=true"
      ]
      ports = [
        { internal = 9092, external = 9092 },
        { internal = 29092, external = 29092 }
      ]
      volumes = []
    }
    mailhog = {
      image = "mailhog/mailhog:latest"
      env = []
      ports = [{ internal = 1025, external = 1025 }, { internal = 8025, external = 8025 }]
      volumes = []
    }
  }
}

resource "docker_network" "infra_net" {
  name = var.network_name
}

resource "docker_volume" "postgres_data" { name = "explore_postgres_data" }
resource "docker_volume" "mongodb_data" { name = "explore_mongodb_data" }

resource "docker_image" "images" {
  for_each = local.services
  name = each.value.image
  keep_locally = true
}

resource "docker_container" "infra" {
  for_each = local.services
  name  = each.key
  image = docker_image.images[each.key].image_id
  restart = "unless-stopped"
  env = each.value.env
  dynamic "ports" {
    for_each = each.value.ports
    content {
      internal = ports.value.internal
      external = ports.value.external
    }
  }
  dynamic "volumes" {
    for_each = each.value.volumes
    content {
      container_path = volumes.value.container_path
      volume_name = volumes.value.name
    }
  }
  networks_advanced {
    name = docker_network.infra_net.name
  }
}
