from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView

from .views import SignupView
from .forms import LoginForm


app_name = 'accounts'

urlpatterns = [
    path('signup', SignupView.as_view(), name='signup'),
    path('login', LoginView.as_view(template_name='accounts/login.html', form_class=LoginForm, redirect_authenticated_user=True), name='login'),
    path('logout', LogoutView.as_view(), name='logout'),
]