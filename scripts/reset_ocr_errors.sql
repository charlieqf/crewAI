UPDATE file_contents 
SET status='pending', error_message=NULL 
WHERE error_message LIKE '%unexpected keyword argument ''cls''%' 
AND created_at >= '2026-01-20';
