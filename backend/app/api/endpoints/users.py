from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from typing import Optional, List
import logging

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate, UserResponse, UserList
from app.config.database import get_db
from app.config.minio import upload_photo, delete_photo
from app.core.dependencies import validate_image_file

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/", response_model=UserList)
async def get_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """Get all users with pagination"""
    try:
        # Get total count
        count_query = select(User)
        result = await db.execute(count_query)
        total = len(result.scalars().all())
        
        # Get paginated users
        query = select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        users = result.scalars().all()
        
        return UserList(
            total=total,
            users=[UserResponse.model_validate(user.to_dict()) for user in users]
        )
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve users"
        )

@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get user by ID"""
    try:
        query = select(User).where(User.id == user_id)
        result = await db.execute(query)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return UserResponse.model_validate(user.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user"
        )

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    name: str = Form(...),
    email: str = Form(...),
    photo: UploadFile = File(None),
    db: AsyncSession = Depends(get_db)
):
    """Create new user with optional photo"""
    try:
        # Validate input
        user_data = UserCreate(name=name, email=email)
        
        # Check if email already exists
        query = select(User).where(User.email == email)
        result = await db.execute(query)
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Handle photo upload
        photo_url = None
        photo_filename = None
        if photo:
            # Validate image
            await validate_image_file(photo)
            
            # Read file content
            content = await photo.read()
            
            # Upload to MinIO
            photo_url, photo_filename = await upload_photo(
                content,
                photo.filename,
                photo.content_type
            )
        
        # Create user in database
        new_user = User(
            name=user_data.name,
            email=user_data.email,
            photo_url=photo_url,
            photo_filename=photo_filename
        )
        
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        
        logger.info(f"✅ User created: {new_user.email}")
        return UserResponse.model_validate(new_user.to_dict())
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )

@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    photo: UploadFile = File(None),
    db: AsyncSession = Depends(get_db)
):
    """Update user information"""
    try:
        # Get existing user
        query = select(User).where(User.id == user_id)
        result = await db.execute(query)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Validate update data
        update_data = {}
        if name:
            update_data["name"] = name
        if email and email != user.email:
            # Check if new email already exists
            email_query = select(User).where(User.email == email)
            email_result = await db.execute(email_query)
            existing = email_result.scalar_one_or_none()
            
            if existing and str(existing.id) != user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )
            update_data["email"] = email
        
        # Handle photo update
        if photo:
            # Validate image
            await validate_image_file(photo)
            
            # Delete old photo if exists
            if user.photo_filename:
                await delete_photo(user.photo_filename)
            
            # Upload new photo
            content = await photo.read()
            photo_url, photo_filename = await upload_photo(
                content,
                photo.filename,
                photo.content_type
            )
            update_data["photo_url"] = photo_url
            update_data["photo_filename"] = photo_filename
        
        # Update user in database
        if update_data:
            stmt = update(User).where(User.id == user_id).values(**update_data)
            await db.execute(stmt)
            await db.commit()
            
            # Get updated user
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one()
        
        logger.info(f"✅ User updated: {user.email}")
        return UserResponse.model_validate(user.to_dict())
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user"
        )

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete user and associated photo"""
    try:
        # Get user
        query = select(User).where(User.id == user_id)
        result = await db.execute(query)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Delete photo from MinIO if exists
        if user.photo_filename:
            await delete_photo(user.photo_filename)
        
        # Delete user from database
        stmt = delete(User).where(User.id == user_id)
        await db.execute(stmt)
        await db.commit()
        
        logger.info(f"✅ User deleted: {user.email}")
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user"
        )
