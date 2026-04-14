from django.urls import path, reverse_lazy
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth import views as auth_views

from .views import SignupView
from .forms import LoginForm


app_name = 'accounts'

urlpatterns = [
    path('signup', SignupView.as_view(), name='signup'),
    path('login', LoginView.as_view(
        template_name='accounts/login.html', 
        form_class=LoginForm, 
        redirect_authenticated_user=True), 
        name='login'),
    path('logout', LogoutView.as_view(), name='logout'),
    path('reset-password/', 
        auth_views.PasswordResetView.as_view(
            template_name='accounts/password_reset_form.html',
            email_template_name='accounts/password_reset_email.html',
            success_url=reverse_lazy('accounts:password_reset_done'),
            extra_context={'domain': '127.0.0.1:8000'}
        ), 
        name='password_reset'),
    path('reset-password/done/', 
        auth_views.PasswordResetDoneView.as_view(
            template_name='accounts/password_reset_done.html'
        ), 
        name='password_reset_done'),
    path('reset/<uidb64>/<token>/', 
        auth_views.PasswordResetConfirmView.as_view(
            template_name='accounts/password_reset_confirm.html',
            success_url=reverse_lazy('accounts:password_reset_complete')
        ), 
        name='password_reset_confirm'),
    path('reset/done/', 
        auth_views.PasswordResetCompleteView.as_view(
            template_name='accounts/password_reset_complete.html'
        ), 
        name='password_reset_complete'),
]