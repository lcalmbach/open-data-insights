# postgres environment
## url
postgres://u3nglacia7tasm:p9a2eddbb22cad12f0303f612f75a514ae4015f0758deaa140d1c5d69c182eff5@c3hsmn51hjafhh.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/der1sicllkuf1v

pgAdmin Field	Value taken from URL
Host name	c3hsmn51hjafhh.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com
Port	5432
Username	u3nglacia7tasm
Password	p9a2eddbb22cad12f0303f612f75a514ae4015f0758deaa140d1c5d69c182eff5
Database name	der1sicllkuf1v
Maintenance DB	postgres

 pg_dump -Fc --no-acl --no-owner -h localhost -U postgres postgres > data_news.dump

pg_restore --verbose --clean --no-acl --no-owner \
  -h c3hsmn51hjafhh.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com \
  -p 5432 \
  -U u3nglacia7tasm \
  -d der1sicllkuf1v \
  data_news.dump