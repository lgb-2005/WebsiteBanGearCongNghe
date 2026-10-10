from django.urls import path

from . import views

app_name = 'chatbot'

urlpatterns = [
    path('api/message/', views.chat_api, name='chat_api'),
    path('api/history/', views.history_api, name='history_api'),
    path('api/new/', views.new_conversation_api, name='new_conversation_api'),
]
